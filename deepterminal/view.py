"""Terminal widget: a PTY on one side, a painted pyte screen on the other."""

from __future__ import annotations

import os
import re

import pyte
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFocusEvent,
    QClipboard,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QApplication, QMenu, QScrollBar, QWidget

from .config import Config, default_font_family, get_theme
from .emulator import TerminalScreen, make_emulator
from .ptyproc import PtyProcess
from .shells import ShellProfile, build_environment

PAD_X = 8
PAD_Y = 8
SCROLLBAR_WIDTH = 10
REPAINT_MS = 8
BLINK_MS = 530
WHEEL_LINES = 3
CORNER_RADIUS = 10.0
AUTO_CLEAR_MS = 300
PROMPT_INJECT_DELAY_MS = 50

_CTRL = Qt.KeyboardModifier.ControlModifier
_SHIFT = Qt.KeyboardModifier.ShiftModifier
_ALT = Qt.KeyboardModifier.AltModifier

_BASE_COLOR_NAMES = {"black", "red", "green", "brown", "blue", "magenta", "cyan", "white"}


def _modifier_argument(modifiers: Qt.KeyboardModifier) -> int:
    value = 1
    if modifiers & _SHIFT:
        value += 1
    if modifiers & _ALT:
        value += 2
    if modifiers & _CTRL:
        value += 4
    return value


def encode_key(event: QKeyEvent, app_cursor: bool) -> bytes | None:
    """Translate a key press into the byte sequence a terminal sends."""
    key = event.key()
    modifiers = event.modifiers()
    ctrl = bool(modifiers & _CTRL)
    alt = bool(modifiers & _ALT)
    shift = bool(modifiers & _SHIFT)
    argument = _modifier_argument(modifiers)

    if key == Qt.Key.Key_Escape:
        return b"\x1b"
    if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        return b"\r"
    if key == Qt.Key.Key_Tab:
        return b"\t"
    if key == Qt.Key.Key_Backtab:
        return b"\x1b[Z"
    if key == Qt.Key.Key_Backspace:
        return b"\x08" if ctrl else b"\x7f"
    if key == Qt.Key.Key_Delete:
        return _tilde_sequence(3, argument)
    if key == Qt.Key.Key_Insert:
        return _tilde_sequence(2, argument)
    if key == Qt.Key.Key_PageUp:
        return _tilde_sequence(5, argument)
    if key == Qt.Key.Key_PageDown:
        return _tilde_sequence(6, argument)

    if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Right, Qt.Key.Key_Left):
        final = {
            Qt.Key.Key_Up: "A",
            Qt.Key.Key_Down: "B",
            Qt.Key.Key_Right: "C",
            Qt.Key.Key_Left: "D",
        }[key]
        return _cursor_sequence(final, argument, app_cursor)
    if key == Qt.Key.Key_Home:
        return _cursor_sequence("H", argument, app_cursor)
    if key == Qt.Key.Key_End:
        return _cursor_sequence("F", argument, app_cursor)

    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F4:
        final = {Qt.Key.Key_F1: "P", Qt.Key.Key_F2: "Q", Qt.Key.Key_F3: "R", Qt.Key.Key_F4: "S"}[key]
        if argument == 1:
            return ("\x1b" + final).encode()
        return f"\x1b[1;{argument}{final}".encode()
    if Qt.Key.Key_F5 <= key <= Qt.Key.Key_F12:
        code = {
            Qt.Key.Key_F5: 15,
            Qt.Key.Key_F6: 17,
            Qt.Key.Key_F7: 18,
            Qt.Key.Key_F8: 19,
            Qt.Key.Key_F9: 20,
            Qt.Key.Key_F10: 21,
            Qt.Key.Key_F11: 23,
            Qt.Key.Key_F12: 24,
        }[key]
        return _tilde_sequence(code, argument)

    if ctrl and not alt:
        if key == Qt.Key.Key_Space:
            return b"\x00"
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return bytes([key - Qt.Key.Key_A + 1])
        if key == Qt.Key.Key_BracketLeft:
            return b"\x1b"
        if key == Qt.Key.Key_Backslash:
            return b"\x1c"
        if key == Qt.Key.Key_BracketRight:
            return b"\x1d"
        if key == Qt.Key.Key_AsciiCircum:
            return b"\x1e"
        if key == Qt.Key.Key_Underscore:
            return b"\x1f"
        if key == Qt.Key.Key_Slash:
            return b"\x1f"

    text = event.text()
    if text:
        # Control combinations arrive as control characters on some platforms;
        # never forward those twice. AltGr arrives as Ctrl+Alt text and must
        # not gain an ESC prefix.
        if any(ord(character) < 0x20 for character in text) and not alt:
            return None
        if alt and not ctrl:
            return b"\x1b" + text.encode("utf-8")
        return text.encode("utf-8")
    return None


def _cursor_sequence(final: str, argument: int, app_cursor: bool) -> bytes:
    if argument == 1:
        prefix = "\x1bO" if app_cursor else "\x1b["
        return (prefix + final).encode()
    return f"\x1b[1;{argument}{final}".encode()


def _tilde_sequence(code: int, argument: int) -> bytes:
    if argument == 1:
        return f"\x1b[{code}~".encode()
    return f"\x1b[{code};{argument}~".encode()


class TerminalView(QWidget):
    """One terminal tab: shell process, emulator, rendering and input."""

    title_changed = pyqtSignal(str)
    bell = pyqtSignal()
    process_exited = pyqtSignal(int)
    restart_requested = pyqtSignal()
    size_changed = pyqtSignal()
    find_requested = pyqtSignal()

    def __init__(self, config: Config, profile: ShellProfile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.profile = profile
        self.theme = config.theme()

        self.emulator, self.stream = make_emulator(80, 24, config.get_int("scrollback"))
        self.pty: PtyProcess | None = None
        self._exited = False
        self._last_title = ""
        self._seen_scroll = 0
        self._scroll_offset = 0
        self._style_cache: dict[tuple, tuple] = {}
        self._color_cache: dict[str, QColor] = {}
        self._preedit = ""
        self._blink_phase = True
        self._selection: tuple[int, int, int, int] | None = None  # top_fb, top_col, bottom_fb, bottom_col
        self._sel_anchor: tuple[int, int] | None = None
        self._mouse_down = False
        self._mouse_button = 0
        self._search_query = ""
        self._search_matches: list[tuple[int, int, int]] = []
        self._search_index = -1
        self._shell_ready = False

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setAutoFillBackground(False)

        self._scrollbar = QScrollBar(Qt.Orientation.Vertical, self)
        self._scrollbar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scrollbar.setSingleStep(1)
        self._scrollbar.valueChanged.connect(self._on_scrollbar)

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(BLINK_MS)
        self._blink_timer.timeout.connect(self._blink)

        self._repaint_timer = QTimer(self)
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.setInterval(REPAINT_MS)
        self._repaint_timer.timeout.connect(self.update)

        self._search_refresh_timer = QTimer(self)
        self._search_refresh_timer.setSingleShot(True)
        self._search_refresh_timer.setInterval(180)
        self._search_refresh_timer.timeout.connect(self._refresh_search)

        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.setInterval(AUTO_CLEAR_MS)
        self._clear_timer.timeout.connect(self._auto_clear)

        self.emulator.on_bell = self._on_bell
        self.emulator.on_reply = self._on_emulator_reply

        self._apply_font()
        self._apply_theme()
        self._start_shell()

    # -- shell lifecycle -------------------------------------------------
    def _start_shell(self) -> None:
        self._shell_ready = False
        try:
            pty = PtyProcess(
                self.profile.argv,
                self._working_directory(),
                build_environment(),
                self.emulator.lines,
                self.emulator.columns,
                self,
                echo_off=self.profile.echo_off,
            )
        except Exception as error:  # pragma: no cover - defensive
            self._show_error(str(error))
            return
        self.pty = pty
        pty.output.connect(self._on_output)
        pty.exited.connect(self._on_process_exit)
        pty.start()
        self._exited = False
        notice = getattr(self, "_pending_notice", "")
        if notice:
            self._pending_notice = ""
            self._message("\r\n" + notice + "\r\n")
        if self.profile.prompt_command:
            # Wait a moment so the child process has disabled ECHO before the
            # setup is written; writing immediately races the fork and can
            # echo the raw "PS1=..." line onto the screen.
            self._prompt_timer = QTimer(self)
            self._prompt_timer.setSingleShot(True)
            self._prompt_timer.setInterval(PROMPT_INJECT_DELAY_MS)
            self._prompt_timer.timeout.connect(self._write_prompt)
            self._prompt_timer.start()
        startup = self.config.get_str("startup_cmd")
        if startup.strip() != "":
            # Wait until the shell is up (and echo is restored) so the
            # startup command is echoed and executed like a typed line.
            self._startup_timer = QTimer(self)
            self._startup_timer.setSingleShot(True)
            self._startup_timer.setInterval(150)
            self._startup_timer.timeout.connect(lambda command=startup: self._run_startup(command))
            self._startup_timer.start()
        self._blink_timer.start()
        self.setFocus()

    def _run_startup(self, command: str) -> None:
        if self.pty is not None and not self._exited:
            self.pty.write(command.encode("utf-8") + b"\r")

    def _write_prompt(self) -> None:
        if self.pty is not None and not self._exited and self.profile.prompt_command:
            self.pty.write(self.profile.prompt_command.encode("utf-8"))

    def _working_directory(self) -> str:
        path = self.config.working_dir()
        if os.path.isdir(path):
            return path
        fallback = os.path.expanduser("~")
        self._pending_notice = f"[DeepTerminal] {path} is not a directory; starting in {fallback}."
        return fallback

    def restart(self) -> None:
        self.shutdown()
        self.emulator.reset()
        self.stream = pyte.ByteStream(self.emulator)
        self._scroll_offset = 0
        self._seen_scroll = 0
        self._selection = None
        self._last_title = ""
        self._exited = False
        self.title_changed.emit(self.profile.label)
        self._start_shell()
        self._sync_scrollbar()
        self.update()

    def shutdown(self) -> None:
        self._blink_timer.stop()
        self._repaint_timer.stop()
        self._search_refresh_timer.stop()
        self._clear_timer.stop()
        startup_timer = getattr(self, "_startup_timer", None)
        if startup_timer is not None:
            startup_timer.stop()
        prompt_timer = getattr(self, "_prompt_timer", None)
        if prompt_timer is not None:
            prompt_timer.stop()
        if self.pty is not None:
            try:
                self.pty.output.disconnect(self._on_output)
                self.pty.exited.disconnect(self._on_process_exit)
            except (TypeError, RuntimeError):
                pass
            self.pty.terminate()
            self.pty = None

    # -- process signals -------------------------------------------------
    def _on_output(self, data: bytes) -> None:
        self._shell_ready = True
        try:
            self.stream.feed(data)
        except Exception:  # pragma: no cover - malformed sequences must not kill the tab
            pass
        if self.emulator.alt_screen and self._scroll_offset != 0:
            # Full-screen programs always own the visible area.
            self._scroll_offset = 0
        scroll_delta = self.emulator.scroll_count - self._seen_scroll
        if scroll_delta > 0:
            self._seen_scroll = self.emulator.scroll_count
            if self._scroll_offset > 0:
                self._scroll_offset += scroll_delta
        self._sync_scrollbar()
        self._sync_title()
        if self._search_query.strip() != "" and not self._search_refresh_timer.isActive():
            self._search_refresh_timer.start()
        self._schedule_repaint()

    def _on_process_exit(self, code: int) -> None:
        if self._exited:
            return
        self._exited = True
        self._blink_timer.stop()
        self._message(f"\r\n[process exited with code {code}]")
        self.title_changed.emit(f"{self.profile.label} (exited)")
        self.process_exited.emit(code)
        self.update()

    def _on_emulator_reply(self, data: bytes) -> None:
        if self.pty is not None:
            self.pty.write(data)

    def _on_bell(self) -> None:
        QApplication.beep()
        self.bell.emit()

    def _message(self, text: str) -> None:
        try:
            self.stream.feed(text.encode("utf-8"))
        except Exception:  # pragma: no cover
            pass
        self._sync_scrollbar()

    def _show_error(self, text: str) -> None:
        self._exited = True
        self._message(f"\r\n[DeepTerminal] {text}\r\n")
        self.title_changed.emit(f"{self.profile.label} (error)")
        self.update()

    # -- title / scrollbar ----------------------------------------------
    def _sync_title(self) -> None:
        title = getattr(self.emulator, "title", "") or ""
        if title != self._last_title:
            self._last_title = title
            self.title_changed.emit(title)

    def _total_lines(self) -> int:
        return len(self.emulator.history.top) + self.emulator.lines

    def _max_offset(self) -> int:
        if self.emulator.alt_screen:
            return 0
        return max(0, self._total_lines() - self.emulator.lines)

    def _sync_scrollbar(self) -> None:
        maximum = self._max_offset()
        self._scroll_offset = min(self._scroll_offset, maximum)
        self._scrollbar.setRange(0, maximum)
        self._scrollbar.setPageStep(self.emulator.lines)
        self._scrollbar.setValue(maximum - self._scroll_offset)
        self._scrollbar.setVisible(maximum > 0)

    def _on_scrollbar(self, value: int) -> None:
        offset = self._scrollbar.maximum() - value
        if offset != self._scroll_offset:
            self._scroll_offset = offset
            self.update()

    def _scroll_by(self, lines: int) -> None:
        if self.emulator.alt_screen:
            return
        maximum = self._max_offset()
        self._scroll_offset = max(0, min(maximum, self._scroll_offset + lines))
        self._sync_scrollbar()
        self.update()

    # -- appearance ------------------------------------------------------
    def _apply_font(self) -> None:
        family = self.config.get_str("font_family").strip() or default_font_family()
        font = QFont(family)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        font.setPointSize(self.config.get_int("font_size"))
        self.font = font
        metrics = QFontMetricsF(font)
        self._cell_w = max(1.0, float(metrics.horizontalAdvance("M")))
        self._cell_h = max(1.0, float(metrics.height()))
        self._ascent = metrics.ascent()
        self._style_cache.clear()
        self._color_cache.clear()

    def _apply_theme(self) -> None:
        self.theme = self.config.theme()
        self._style_cache.clear()
        self._color_cache.clear()
        self._scrollbar.setStyleSheet(
            "QScrollBar:vertical { background: %(bg)s; width: %(w)dpx; margin: 0; }"
            "QScrollBar::handle:vertical { background: %(border)s; min-height: 24px; border-radius: 4px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }"
            % {"bg": self.theme["bg"], "w": SCROLLBAR_WIDTH, "border": self.theme["border"]}
        )
        self._bg_color = QColor(str(self.theme["bg"]))
        self._bg_rgb = self._bg_color.rgb()
        self.update()

    def apply_settings(self) -> None:
        """Apply live settings (theme, font, blink). Shell needs a new tab."""
        self._apply_font()
        self._apply_theme()
        if self.config.get_bool("cursor_blink") and not self._exited:
            self._blink_timer.start()
        else:
            self._blink_timer.stop()
            self._blink_phase = True
        self._resize_grid()
        self.update()

    # -- geometry --------------------------------------------------------
    def _resize_grid(self) -> None:
        available_width = max(1.0, self.width() - SCROLLBAR_WIDTH - 2 * PAD_X)
        available_height = max(1.0, self.height() - 2 * PAD_Y)
        columns = max(2, int(available_width // self._cell_w))
        lines = max(2, int(available_height // self._cell_h))
        if (lines, columns) == (self.emulator.lines, self.emulator.columns):
            return
        self.emulator.resize(lines, columns)
        if self.pty is not None:
            self.pty.resize(lines, columns)
        self._schedule_auto_clear()
        self._scroll_offset = min(self._scroll_offset, self._max_offset())
        if self._search_query.strip() != "":
            index = self._search_index
            self.set_search(self._search_query, jump=False)
            if self._search_matches:
                self._search_index = min(max(0, index), len(self._search_matches) - 1)
        self._sync_scrollbar()
        self.size_changed.emit()

    def _schedule_auto_clear(self) -> None:
        """After a resize settles, refresh the shell with a clear-screen.

        Reflowing keeps every character, but the shell redraws its prompt on
        SIGWINCH and can leave it stranded at the bottom of the screen. Sending
        Ctrl+L (readline's clear-screen) repaints a fresh prompt at the top,
        exactly like typing ``clear`` — without polluting shell history.
        """
        if self._shell_ready and not self._exited and not self.emulator.alt_screen:
            self._clear_timer.start()

    def _auto_clear(self) -> None:
        if self._shell_ready and not self._exited and not self.emulator.alt_screen:
            self._write_input(b"\x0c")

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._scrollbar.setGeometry(self.width() - SCROLLBAR_WIDTH, 0, SCROLLBAR_WIDTH, self.height())
        self._resize_grid()
        super().resizeEvent(event)

    # -- painting --------------------------------------------------------
    def _color(self, value: object, foreground: bool) -> QColor:
        palette = self.theme["palette"]
        key = str(value) if value not in (None, "default") else "__default__"
        cache_key = f"{key}|{'fg' if foreground else 'bg'}"
        cached = self._color_cache.get(cache_key)
        if cached is not None:
            return cached
        if key == "__default__":
            color = QColor(str(self.theme["fg"] if foreground else self.theme["bg"]))
        elif key in palette:
            color = QColor(str(palette[key]))
        elif re.fullmatch(r"[0-9a-fA-F]{6}", key):
            color = QColor("#" + key)
        else:
            color = QColor(str(self.theme["fg"] if foreground else self.theme["bg"]))
        self._color_cache[cache_key] = color
        return color

    def _style(self, cell) -> tuple[QColor, QColor, QFont, bool, bool]:
        key = (cell.fg, cell.bg, cell.bold, cell.italics, cell.underscore, cell.strikethrough, cell.reverse)
        cached = self._style_cache.get(key)
        if cached is not None:
            return cached
        foreground_name = cell.fg
        background_name = cell.bg
        if cell.reverse:
            foreground_name, background_name = background_name, foreground_name
        if cell.bold and isinstance(foreground_name, str) and foreground_name in _BASE_COLOR_NAMES:
            candidate = "bright" + foreground_name
            if candidate in self.theme["palette"]:
                foreground_name = candidate
        foreground = self._color(foreground_name, True)
        background = self._color(background_name, False)
        font = QFont(self.font)
        if cell.bold:
            font.setWeight(QFont.Weight.Bold)
        if cell.italics:
            font.setItalic(True)
        style = (foreground, background, font, bool(cell.underscore), bool(cell.strikethrough))
        self._style_cache[key] = style
        return style

    def _line_at(self, fb: int, history) -> object | None:
        screen_lines = self.emulator.lines
        if fb < 0:
            return None
        if fb < screen_lines:
            return self.emulator.buffer[screen_lines - 1 - fb]
        index = fb - screen_lines
        if 0 <= index < len(history):
            return history[len(history) - 1 - index]
        return None

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if CORNER_RADIUS > 0:
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(self.rect()), CORNER_RADIUS, CORNER_RADIUS)
            painter.setClipPath(clip)
        painter.fillRect(self.rect(), self._bg_color)

        cell_w, cell_h = self._cell_w, self._cell_h
        rows, columns = self.emulator.lines, self.emulator.columns
        history = list(self.emulator.history.top)
        total = len(history) + rows
        offset = min(self._scroll_offset, max(0, total - rows))

        for view_row in range(rows):
            fb = offset + rows - 1 - view_row
            line = self._line_at(fb, history)
            if line is None:
                continue
            y = PAD_Y + view_row * cell_h
            run_start = 0
            run_text: list[str] = []
            run_style = None
            for column in range(columns):
                cell = line[column]
                style = self._style(cell)
                if style != run_style:
                    if run_style is not None:
                        self._draw_run(painter, PAD_X + run_start * cell_w, y, run_text, run_style, cell_w, cell_h)
                    run_style = style
                    run_start = column
                    run_text = []
                run_text.append(cell.data)
            if run_style is not None:
                self._draw_run(painter, PAD_X + run_start * cell_w, y, run_text, run_style, cell_w, cell_h)

        self._paint_selection(painter, history, rows, cell_w, cell_h, offset)
        self._paint_search(painter, rows, cell_w, cell_h, offset)
        self._paint_preedit(painter, history, rows, cell_w, cell_h, offset)
        if offset == 0:
            self._paint_cursor(painter, cell_w, cell_h)
        painter.end()

    def _draw_run(self, painter: QPainter, x: float, y: float, text: list[str], style: tuple, cell_w: float, cell_h: float) -> None:
        foreground, background, font, underline, strike = style
        text_value = "".join(text)
        if text_value == "":
            return
        if background.rgb() != self._bg_rgb:
            painter.fillRect(QRectF(x, y, cell_w * len(text), cell_h), background)
        painter.setFont(font)
        painter.setPen(QPen(foreground))
        painter.drawText(QPointF(x, y + self._ascent), text_value)
        if underline:
            painter.drawLine(QPointF(x, y + self._ascent + 1), QPointF(x + cell_w * len(text), y + self._ascent + 1))
        if strike:
            painter.drawLine(QPointF(x, y + self._ascent * 0.6), QPointF(x + cell_w * len(text), y + self._ascent * 0.6))

    def _paint_selection(self, painter, history, rows, cell_w, cell_h, offset) -> None:
        if self._selection is None:
            return
        top_fb, top_column, bottom_fb, bottom_column = self._selection
        color = QColor(str(self.theme["selection"]))
        color.setAlpha(160)
        painter.setPen(Qt.PenStyle.NoPen)
        for fb in range(bottom_fb, top_fb + 1):
            view_row = offset + rows - 1 - fb
            if view_row < 0 or view_row >= rows:
                continue
            start = top_column if fb == top_fb else 0
            end = bottom_column if fb == bottom_fb else self.emulator.columns - 1
            if end < start:
                continue
            painter.fillRect(
                QRectF(PAD_X + start * cell_w, PAD_Y + view_row * cell_h, (end - start + 1) * cell_w, cell_h),
                color,
            )

    def _paint_preedit(self, painter, history, rows, cell_w, cell_h, offset) -> None:
        if self._preedit == "" or offset != 0:
            return
        cursor = self.emulator.cursor
        x = PAD_X + cursor.x * cell_w
        y = PAD_Y + cursor.y * cell_h
        width = max(cell_w, len(self._preedit) * cell_w)
        painter.fillRect(QRectF(x, y, width, cell_h), QColor(str(self.theme["selection"])))
        painter.setPen(QPen(QColor(str(self.theme["selection_text"]))))
        painter.drawText(QPointF(x, y + self._ascent), self._preedit)
        painter.drawLine(QPointF(x, y + self._ascent + 1), QPointF(x + width, y + self._ascent + 1))

    def _paint_cursor(self, painter: QPainter, cell_w: float, cell_h: float) -> None:
        cursor = self.emulator.cursor
        if getattr(cursor, "hidden", False) or self._exited:
            return
        if not self._blink_phase:
            return
        column = min(cursor.x, self.emulator.columns - 1)
        x = PAD_X + column * cell_w
        y = PAD_Y + cursor.y * cell_h
        rect = QRectF(x, y, cell_w, cell_h)
        focused = self.hasFocus()
        if focused:
            painter.fillRect(rect, QColor(str(self.theme["cursor"])))
            line = self.emulator.buffer[cursor.y]
            cell = line[column]
            painter.setPen(QPen(QColor(str(self.theme["cursor_text"]))))
            painter.setFont(self.font)
            painter.drawText(QPointF(x, y + self._ascent), cell.data or " ")
        else:
            painter.setPen(QPen(QColor(str(self.theme["cursor"]))))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    def _blink(self) -> None:
        if not self.hasFocus() or not self.config.get_bool("cursor_blink"):
            self._blink_phase = True
            return
        self._blink_phase = not self._blink_phase
        self.update()

    def _schedule_repaint(self) -> None:
        if not self._repaint_timer.isActive():
            self._repaint_timer.start()

    # -- keyboard --------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt naming
        modifiers = event.modifiers()
        ctrl = bool(modifiers & _CTRL)
        shift = bool(modifiers & _SHIFT)
        key = event.key()

        if ctrl and shift and key == Qt.Key.Key_C:
            self.copy_selection()
            return
        if ctrl and shift and key == Qt.Key.Key_V:
            self.paste_clipboard()
            return
        if shift and key == Qt.Key.Key_Insert:
            self.paste_selection()
            return
        if ctrl and key == Qt.Key.Key_Insert:
            self.copy_selection()
            return
        if ctrl and key in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
            self.zoom(1)
            return
        if ctrl and key == Qt.Key.Key_Minus:
            self.zoom(-1)
            return
        if ctrl and key == Qt.Key.Key_0:
            self.zoom(0)
            return

        data = encode_key(event, self.emulator.app_cursor)
        if data:
            self._write_input(data)
            event.accept()
            return
        super().keyPressEvent(event)

    def _write_input(self, data: bytes) -> None:
        if self.pty is None or data == b"":
            return
        if self._scroll_offset > 0:
            self._scroll_offset = 0
            self._sync_scrollbar()
        self.pty.write(data)
        self.update()

    def zoom(self, direction: int) -> None:
        from .config import DEFAULTS

        if direction == 0:
            size = int(DEFAULTS["font_size"])
        else:
            size = max(6, min(32, self.config.get_int("font_size") + direction))
        self.config.set("font_size", size)
        self._apply_font()
        self._resize_grid()
        self.update()

    def inputMethodEvent(self, event) -> None:  # noqa: N802 - Qt naming
        commit = event.commitString()
        if commit:
            self._write_input(commit.encode("utf-8"))
        self._preedit = event.preeditString()
        self.update()

    def inputMethodQuery(self, query):  # noqa: N802 - Qt naming
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            return self._cursor_rect()
        if query == Qt.InputMethodQuery.ImEnabled:
            return True
        if query == Qt.InputMethodQuery.ImCursorPosition:
            return self.emulator.cursor.x
        if query == Qt.InputMethodQuery.ImHints:
            return Qt.InputMethodHint.ImhNoAutoUppercase | Qt.InputMethodHint.ImhNoPredictiveText
        return None

    def _cursor_rect(self) -> QRect:
        cursor = self.emulator.cursor
        column = min(cursor.x, self.emulator.columns - 1)
        return QRect(
            int(PAD_X + column * self._cell_w),
            int(PAD_Y + cursor.y * self._cell_h),
            int(self._cell_w),
            int(self._cell_h),
        )

    # -- clipboard / selection ------------------------------------------
    def _ordered_selection(self) -> tuple[int, int, int, int] | None:
        if self._selection is None:
            return None
        return self._selection

    def _line_text(self, fb: int, history) -> str:
        line = self._line_at(fb, history)
        if line is None:
            return ""
        return "".join(line[column].data for column in range(self.emulator.columns))

    def selection_text(self) -> str:
        selection = self._ordered_selection()
        if selection is None:
            return ""
        top_fb, top_column, bottom_fb, bottom_column = selection
        history = list(self.emulator.history.top)
        rows = []
        for fb in range(top_fb, bottom_fb - 1, -1):
            line = self._line_at(fb, history)
            if line is None:
                rows.append("")
                continue
            start = top_column if fb == top_fb else 0
            end = bottom_column if fb == bottom_fb else self.emulator.columns - 1
            text = "".join(line[column].data for column in range(start, end + 1))
            rows.append(text.rstrip())
        return "\n".join(rows)

    def copy_selection(self) -> None:
        text = self.selection_text()
        if text != "":
            QGuiApplication.clipboard().setText(text)

    def select_all(self) -> None:
        total = self._total_lines()
        self._selection = (total - 1, 0, 0, self.emulator.columns - 1)
        self.update()

    def paste_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text == "":
            return
        self._paste_text(text)

    def paste_selection(self) -> None:
        clipboard = QGuiApplication.clipboard()
        text = clipboard.text(QClipboard.Mode.Selection) if clipboard.supportsSelection() else ""
        if text == "":
            text = clipboard.text()
        if text != "":
            self._paste_text(text)

    def _paste_text(self, text: str) -> None:
        normalized = text.replace("\r\n", "\r").replace("\n", "\r")
        data = normalized.encode("utf-8")
        if self.emulator.bracketed_paste:
            data = b"\x1b[200~" + data + b"\x1b[201~"
        self._write_input(data)

    # -- mouse -----------------------------------------------------------
    def _cell_at(self, point: QPoint) -> tuple[int, int] | None:
        if point.x() < PAD_X or point.y() < PAD_Y:
            return None
        column = int((point.x() - PAD_X) // self._cell_w)
        view_row = int((point.y() - PAD_Y) // self._cell_h)
        column = max(0, min(self.emulator.columns - 1, column))
        view_row = max(0, min(self.emulator.lines - 1, view_row))
        fb = self._scroll_offset + self.emulator.lines - 1 - view_row
        return fb, column

    def _mouse_command(self, fb: int, column: int, button: int, press: bool, motion: bool = False) -> None:
        """Report a mouse event using screen coordinates (not scrollback)."""
        if self.pty is None:
            return
        row = self.emulator.lines - fb  # 1-based from the top of the screen
        modifiers = 0
        state = QGuiApplication.keyboardModifiers()
        if state & _ALT:
            modifiers += 8
        if state & _CTRL:
            modifiers += 16
        if state & _SHIFT:
            modifiers += 4
        code = button + modifiers
        if motion:
            code += 32
        if not press and not self.emulator.mouse_sgr:
            # X10 reports every release as button 3.
            code = 3 + modifiers
        if self.emulator.mouse_sgr:
            final = "M" if press else "m"
            self.pty.write(f"\x1b[<{code};{column + 1};{row}{final}".encode())
        else:
            x = min(222, column + 1)
            y = min(222, row)
            self.pty.write(b"\x1b[M" + bytes([32 + code, 32 + x, 32 + y]))

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.setFocus()
        modifiers = event.modifiers()
        reporting = self.emulator.mouse_mode != 0 and not (modifiers & _SHIFT) and self._scroll_offset == 0
        cell = self._cell_at(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton:
            if reporting and cell is not None:
                button = 0
                if modifiers & _ALT:
                    pass
                self._mouse_down = True
                self._mouse_button = button
                self._mouse_command(cell[0], cell[1], button, True)
                return
            if cell is not None:
                self._sel_anchor = cell
                self._selection = (cell[0], cell[1], cell[0], cell[1])
                self.update()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            if reporting and cell is not None:
                self._mouse_command(cell[0], cell[1], 1, True)
                self._mouse_command(cell[0], cell[1], 1, False)
            else:
                self.paste_selection()
            return
        if event.button() == Qt.MouseButton.RightButton:
            if reporting and cell is not None:
                self._mouse_down = True
                self._mouse_button = 2
                self._mouse_command(cell[0], cell[1], 2, True)
                return
            self._show_menu(event.position().toPoint())
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        cell = self._cell_at(event.position().toPoint())
        if cell is None:
            return
        reporting = self.emulator.mouse_mode != 0 and not (event.modifiers() & _SHIFT) and self._scroll_offset == 0
        if reporting and self.emulator.mouse_mode in (1002, 1003):
            if self._mouse_down:
                self._mouse_command(cell[0], cell[1], self._mouse_button, True, motion=True)
            elif self.emulator.mouse_mode == 1003:
                self._mouse_command(cell[0], cell[1], 3, True, motion=True)
            return
        if self._sel_anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            anchor = self._sel_anchor
            if cell[0] > anchor[0] or (cell[0] == anchor[0] and cell[1] >= anchor[1]):
                self._selection = (cell[0], cell[1], anchor[0], anchor[1])
            else:
                self._selection = (anchor[0], anchor[1], cell[0], cell[1])
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        cell = self._cell_at(event.position().toPoint())
        reporting = self.emulator.mouse_mode != 0 and not (event.modifiers() & _SHIFT) and self._scroll_offset == 0
        if self._mouse_down and cell is not None and reporting:
            self._mouse_command(cell[0], cell[1], self._mouse_button, False)
            self._mouse_down = False
            return
        self._sel_anchor = None
        if self._selection is not None:
            top_fb, top_column, bottom_fb, bottom_column = self._selection
            if (top_fb, top_column) == (bottom_fb, bottom_column):
                self._selection = None
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt naming
        reporting = self.emulator.mouse_mode != 0 and not (event.modifiers() & _SHIFT) and self._scroll_offset == 0
        if reporting:
            return  # The application already received the clicks.
        cell = self._cell_at(event.position().toPoint())
        if cell is None:
            return
        history = list(self.emulator.history.top)
        text = self._line_text(cell[0], history)
        start = end = cell[1]
        while start > 0 and text[start - 1].isalnum():
            start -= 1
        while end + 1 < len(text) and text[end + 1].isalnum():
            end += 1
        self._selection = (cell[0], end, cell[0], start)
        self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt naming
        delta = event.angleDelta().y()
        if delta == 0:
            return
        reporting = self.emulator.mouse_mode != 0 and not (event.modifiers() & _SHIFT)
        if reporting:
            button = 64 if delta > 0 else 65
            cell = self._cell_at(event.position().toPoint()) or (0, 0)
            self._mouse_command(cell[0], cell[1], button, True)
            return
        self._scroll_by(WHEEL_LINES if delta > 0 else -WHEEL_LINES)

    def _show_menu(self, point: QPoint) -> None:
        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        copy_action.setEnabled(self._selection is not None)
        copy_action.triggered.connect(self.copy_selection)
        paste_action = menu.addAction("Paste")
        paste_action.triggered.connect(self.paste_clipboard)
        menu.addSeparator()
        select_all = menu.addAction("Select All")
        select_all.triggered.connect(self.select_all)
        clear_screen = menu.addAction("Clear Screen")
        clear_screen.triggered.connect(lambda: self._write_input(b"\x0c"))
        clear_scrollback = menu.addAction("Clear Scrollback")
        clear_scrollback.triggered.connect(self.clear_scrollback)
        reset = menu.addAction("Reset Terminal")
        reset.triggered.connect(self.reset_terminal)
        menu.addSeparator()
        find = menu.addAction("Find…")
        find.triggered.connect(self.find_requested.emit)
        restart = menu.addAction("Restart Shell")
        restart.triggered.connect(self.restart_requested.emit)
        menu.exec(self.mapToGlobal(point))

    def clear_scrollback(self) -> None:
        self.emulator.history.top.clear()
        self.emulator.history.bottom.clear()
        self._scroll_offset = 0
        self._sync_scrollbar()
        self.update()

    def reset_terminal(self) -> None:
        self.emulator.reset()
        self.stream = pyte.ByteStream(self.emulator)
        self._selection = None
        self._scroll_offset = 0
        self._sync_scrollbar()
        self.update()

    # -- search ----------------------------------------------------------
    def _iter_document_lines(self):
        history = list(self.emulator.history.top)
        total = len(history) + self.emulator.lines
        for fb in range(total - 1, -1, -1):
            line = self._line_at(fb, history)
            if line is None:
                continue
            yield fb, "".join(line[column].data for column in range(self.emulator.columns))

    def set_search(self, query: str, jump: bool = True) -> int:
        """Highlight every occurrence of ``query`` in screen and scrollback."""
        self._search_query = query
        self._search_matches = []
        self._search_index = -1
        if query.strip() != "":
            needle = query.lower()
            limit = 5000
            for fb, text in self._iter_document_lines():
                lower = text.lower()
                start = 0
                while len(self._search_matches) < limit:
                    found = lower.find(needle, start)
                    if found < 0:
                        break
                    self._search_matches.append((fb, found, found + len(query) - 1))
                    start = found + max(1, len(needle))
                if len(self._search_matches) >= limit:
                    break
        if jump and self._search_matches:
            self._search_index = 0
            self._search_jump()
        self.update()
        return len(self._search_matches)

    def search_step(self, delta: int) -> None:
        if not self._search_matches:
            return
        self._search_index = (self._search_index + delta) % len(self._search_matches)
        self._search_jump()

    def search_matches(self) -> list[tuple[int, int, int]]:
        return self._search_matches

    def search_position(self) -> int:
        return self._search_index

    def clear_search(self) -> None:
        self._search_query = ""
        self._search_matches = []
        self._search_index = -1
        self.update()

    def _refresh_search(self) -> None:
        if self._search_query.strip() == "":
            return
        index = self._search_index
        self.set_search(self._search_query, jump=False)
        if self._search_matches:
            self._search_index = min(max(0, index), len(self._search_matches) - 1)
        self.update()

    def _search_jump(self) -> None:
        if not self._search_matches or self._search_index < 0:
            return
        fb = self._search_matches[self._search_index][0]
        rows = self.emulator.lines
        maximum = self._max_offset()
        self._scroll_offset = max(0, min(maximum, fb - rows // 2))
        self._sync_scrollbar()
        self.update()

    def _paint_search(self, painter: QPainter, rows: int, cell_w: float, cell_h: float, offset: int) -> None:
        if not self._search_matches:
            return
        normal = QColor(255, 214, 0, 80)
        current = QColor(255, 170, 0, 190)
        for index, (fb, start, end) in enumerate(self._search_matches):
            view_row = offset + rows - 1 - fb
            if view_row < 0 or view_row >= rows:
                continue
            painter.fillRect(
                QRectF(PAD_X + start * cell_w, PAD_Y + view_row * cell_h, (end - start + 1) * cell_w, cell_h),
                current if index == self._search_index else normal,
            )

    # -- misc ------------------------------------------------------------
    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt naming
        self._blink_phase = True
        if self.emulator.focus_events and self.pty is not None:
            self.pty.write(b"\x1b[I")
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt naming
        if self.emulator.focus_events and self.pty is not None:
            self.pty.write(b"\x1b[O")
        self.update()
        super().focusOutEvent(event)

    def screen_text(self) -> str:
        return "\n".join(self.emulator.text_of_row(row) for row in range(self.emulator.lines))

    def size_text(self) -> str:
        return f"{self.emulator.columns}x{self.emulator.lines}"

    def selection(self) -> str:
        return self.selection_text()
