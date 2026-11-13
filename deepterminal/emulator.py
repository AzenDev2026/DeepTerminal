"""Terminal emulation on top of pyte.

pyte implements the VT100/xterm command set (cursor addressing, scroll
regions, 256-colour and true-colour SGR, character sets, ...), but it has no
alternate screen, mouse reporting or application cursor keys. This module
adds those pieces so full-screen programs (vim, less, htop, tmux) behave like
they do in a real terminal.
"""

from __future__ import annotations

import copy
from collections import defaultdict, deque
from typing import Callable

import pyte
from pyte.screens import HistoryScreen, Margins, Screen, StaticDefaultDict
from wcwidth import wcwidth


class TerminalScreen(HistoryScreen):
    """A pyte screen with the xterm features pyte leaves out."""

    def __init__(self, columns: int, lines: int, history: int = 5000) -> None:
        super().__init__(columns, lines, history=history)
        self.title = ""
        self._alt_mode = False
        self._saved: tuple | None = None
        self._pending_resize: tuple[int, int] | None = None
        # xterm modes that pyte does not track itself.
        self.app_cursor = False
        self.mouse_mode = 0  # 0 off, 1000 click, 1002 drag, 1003 any motion
        self.mouse_sgr = False
        self.bracketed_paste = False
        self.focus_events = False
        #: Counts lines pushed into scrollback; the view uses it to keep a
        #: scrolled-back viewport anchored while new output arrives.
        self.scroll_count = 0
        #: Hooks installed by the terminal widget.
        self.on_bell: Callable[[], None] | None = None
        self.on_reply: Callable[[bytes], None] | None = None
        #: Line objects (by id) that continue the line above them via a soft
        #: wrap. Used to rejoin wrapped lines when the grid is reflowed.
        self._wrapped_lines: set[int] = set()
        self._in_draw = 0

    # -- pyte hooks ------------------------------------------------------
    def bell(self, *args: object) -> None:
        if self.on_bell is not None:
            self.on_bell()

    def draw(self, data: str) -> None:
        """Track soft wraps: ``linefeed`` called while drawing is a wrap."""
        self._in_draw += 1
        try:
            super().draw(data)
        finally:
            self._in_draw -= 1

    def linefeed(self) -> None:
        soft = self._in_draw > 0
        super().linefeed()
        if soft:
            # The row now under the cursor continues the wrapped line above.
            self._wrapped_lines.add(id(self.buffer[self.cursor.y]))

    def write_process_input(self, data: str) -> None:
        """Answer terminal queries (cursor position, device attributes)."""
        if self.on_reply is not None:
            self.on_reply(data.encode("utf-8", "replace"))

    def set_title(self, param: str) -> None:
        self.title = param

    # -- alternate screen ------------------------------------------------
    def _blank_buffer(self):
        return defaultdict(lambda: StaticDefaultDict(self.default_char))

    def _enter_alt(self, clear: bool) -> None:
        if not self._alt_mode:
            self._saved = (self.buffer, copy.copy(self.cursor), self.margins, self.lines, self.columns)
            self._alt_mode = True
            self.buffer = self._blank_buffer()
            self.cursor_position(0, 0)
            self.margins = None
        elif clear:
            self.buffer.clear()
            self.cursor_position(0, 0)
            self.margins = None

    def _exit_alt(self) -> None:
        if not self._alt_mode or self._saved is None:
            return
        buffer, cursor, margins, saved_lines, saved_columns = self._saved
        self.buffer = buffer
        self.cursor = cursor
        self.margins = margins
        self._alt_mode = False
        self._saved = None
        # The main buffer was saved at its old grid size; reflow it to the
        # size the terminal has now (it may have changed while a full-screen
        # program was active), then apply any resize deferred in alt mode.
        current_lines, current_columns = self.lines, self.columns
        self.lines, self.columns = saved_lines, saved_columns
        if (saved_lines, saved_columns) != (current_lines, current_columns):
            self._reflow(current_lines, current_columns)
        if self._pending_resize is not None:
            pending_lines, pending_columns = self._pending_resize
            self._pending_resize = None
            if (pending_lines, pending_columns) != (self.lines, self.columns):
                self._reflow(pending_lines, pending_columns)

    def resize(self, lines: int | None = None, columns: int | None = None) -> None:
        lines = self.lines if lines is None else max(1, int(lines))
        columns = self.columns if columns is None else max(1, int(columns))
        if self._alt_mode:
            # A full-screen program owns the display and redraws itself when
            # it receives SIGWINCH; only the grid needs updating now. The
            # main buffer is reflowed once the alternate screen is left.
            self._pending_resize = (lines, columns)
            super().resize(lines, columns)
            return
        if (lines, columns) == (self.lines, self.columns):
            return
        self._reflow(lines, columns)

    # -- reflow ----------------------------------------------------------
    def _reflow(self, new_lines: int, new_columns: int) -> None:
        """Reflow scrollback and screen into a new grid without losing text.

        pyte's own ``resize`` clips lines at the right edge and drops screen
        rows at the top, which visibly destroys text when the window changes
        size. This rebuilds the content at the new width instead, re-joining
        lines that were only split by a soft wrap.
        """
        old_lines, old_columns = self.lines, self.columns
        new_lines = max(1, int(new_lines))
        new_columns = max(2, int(new_columns))

        # 1. Gather the whole document: scrollback (oldest first), then the
        #    visible rows (top to bottom), each as a dense cell list, plus a
        #    flag saying whether it continues the line above it.
        rows: list[list[object]] = []
        continuation: list[bool] = []
        for line in self.history.top:
            rows.append([line[x] for x in range(old_columns)])
            continuation.append(id(line) in self._wrapped_lines)
        for y in range(old_lines):
            line = self.buffer[y]
            rows.append([line[x] for x in range(old_columns)])
            continuation.append(id(line) in self._wrapped_lines)

        # 2. Re-join soft-wrapped lines into logical lines, then re-wrap each
        #    logical line to the new width.
        pairs: list[tuple[list[object], bool]] = []
        current: list[object] = []
        for cells, cont in zip(rows, continuation):
            if cont and current:
                current.extend(cells)
            else:
                if current:
                    self._append_reflowed(pairs, self._reflow_line(current, new_columns))
                current = list(cells)
        if current:
            self._append_reflowed(pairs, self._reflow_line(current, new_columns))

        # 3. Split back: the newest `new_lines` rows become the screen, the
        #    rest become scrollback (bounded by the history capacity).
        if len(pairs) <= new_lines:
            history_pairs: list[tuple[list[object], bool]] = []
            screen_pairs = pairs
        else:
            history_pairs = pairs[:-new_lines]
            screen_pairs = pairs[-new_lines:]
        if len(screen_pairs) < new_lines:
            screen_pairs = [([], False) for _ in range(new_lines - len(screen_pairs))] + screen_pairs

        # 4. Rebuild history and screen, and re-derive the wrap flags so a
        #    later reflow can rejoin lines again.
        self._wrapped_lines = set()
        history_lines = []
        for cells, cont in history_pairs:
            line = self._make_line(cells)
            history_lines.append(line)
            if cont:
                self._wrapped_lines.add(id(line))
        self.history = self.history._replace(
            top=deque(history_lines, maxlen=self.history.top.maxlen),
            bottom=deque(maxlen=self.history.bottom.maxlen),
            position=self.history.size,
        )

        self.buffer = defaultdict(lambda: StaticDefaultDict(self.default_char))
        for y, (cells, cont) in enumerate(screen_pairs):
            line = self._make_line(cells)
            self.buffer[y] = line
            if cont:
                self._wrapped_lines.add(id(line))

        self.lines, self.columns = new_lines, new_columns
        self.margins = None
        self.dirty = set(range(new_lines))
        self._cursor_after_reflow()

    @staticmethod
    def _append_reflowed(pairs: list[tuple[list[object], bool]], visual_lines: list[list[object]]) -> None:
        """Append one logical line's visual lines; all but the first continue it."""
        for idx, cells in enumerate(visual_lines):
            pairs.append((cells, idx > 0))

    def _make_line(self, cells: list[object]) -> StaticDefaultDict:
        """Pack a dense cell list into the sparse line type pyte expects."""
        line = StaticDefaultDict(self.default_char)
        for x, cell in enumerate(cells):
            line[x] = cell
        return line

    @staticmethod
    def _cell_is_blank(cell: object) -> bool:
        if cell.data not in ("", " "):
            return False
        return (
            cell.fg == "default"
            and cell.bg == "default"
            and not cell.bold
            and not cell.italics
            and not cell.underscore
            and not cell.strikethrough
            and not cell.reverse
        )

    def _trim_line(self, cells: list[object]) -> list[object]:
        end = len(cells)
        while end > 0 and self._cell_is_blank(cells[end - 1]):
            end -= 1
        # Keep the stub cell of a trailing width-2 glyph so the glyph still
        # occupies both columns after reflow.
        if 0 < end < len(cells):
            if wcwidth(cells[end - 1].data) == 2 and cells[end].data == "":
                end += 1
        return cells[:end]

    def _reflow_line(self, cells: list[object], new_columns: int) -> list[list[object]]:
        """Re-wrap one logical line (dense cells) to ``new_columns`` width."""
        cells = self._trim_line(cells)
        if not cells:
            return [[]]

        lines: list[list[object]] = []
        current: list[object] = []
        width = 0
        i = 0
        count = len(cells)
        while i < count:
            cell = cells[i]
            if cell.data == "":
                # Stub cell of a width-2 glyph: never starts a line on its
                # own, it always travels with the glyph before it.
                if current:
                    current.append(cell)
                i += 1
                continue
            char_width = wcwidth(cell.data)
            if char_width <= 0:
                char_width = 0
            if char_width > 0 and width + char_width > new_columns and current:
                lines.append(current)
                current = []
                width = 0
            current.append(cell)
            width += char_width
            i += 1
            if char_width == 2:
                # A width-2 glyph occupies two cells: keep the trailing stub
                # with it so the glyph is never split across a line break.
                if i < count and cells[i].data == "":
                    current.append(cells[i])
                    i += 1
                else:
                    current.append(cell._replace(data=""))
        if current or not lines:
            lines.append(current)
        return lines

    def _content_length(self, y: int) -> int:
        """Number of cells up to the last non-blank one in a screen row."""
        length = 0
        for x in range(self.columns):
            if not self._cell_is_blank(self.buffer[y][x]):
                length = x + 1
        return length

    def _cursor_after_reflow(self) -> None:
        """Place the cursor at the end of the last row that has content."""
        last_y = self.lines - 1
        last_x = 0
        for y in range(self.lines - 1, -1, -1):
            length = self._content_length(y)
            if length > 0:
                last_y = y
                last_x = min(length, self.columns - 1)
                break
        self.cursor.x = last_x
        self.cursor.y = last_y
        self.cursor.hidden = False

    def index(self) -> None:
        """Scroll up; never put alternate-screen lines into scrollback."""
        if self._alt_mode:
            Screen.index(self)
            return
        top, bottom = self.margins or Margins(0, self.lines - 1)
        if self.cursor.y == bottom:
            self.scroll_count += 1
        super().index()

    def reverse_index(self) -> None:
        if self._alt_mode:
            Screen.reverse_index(self)
            return
        super().reverse_index()

    # -- xterm modes -----------------------------------------------------
    def set_mode(self, *modes: int, **kwargs: bool) -> None:
        if kwargs.get("private"):
            codes = set(modes)
            if 1 in codes:
                self.app_cursor = True
            if 2004 in codes:
                self.bracketed_paste = True
            if 1004 in codes:
                self.focus_events = True
            if 1006 in codes:
                self.mouse_sgr = True
            for code in (1003, 1002, 1000):
                if code in codes:
                    self.mouse_mode = code
                    break
            if codes & {47, 1047, 1049}:
                self._enter_alt(clear=1049 in codes)
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes: int, **kwargs: bool) -> None:
        if kwargs.get("private"):
            codes = set(modes)
            if 1 in codes:
                self.app_cursor = False
            if 2004 in codes:
                self.bracketed_paste = False
            if 1004 in codes:
                self.focus_events = False
            if 1006 in codes:
                self.mouse_sgr = False
            if codes & {1000, 1002, 1003} and self.mouse_mode in codes:
                self.mouse_mode = 0
            if codes & {47, 1047, 1049}:
                self._exit_alt()
        super().reset_mode(*modes, **kwargs)

    def reset(self) -> None:
        # A reset discards both buffers: never leave the alternate screen's
        # contents behind as the new main buffer.
        self._alt_mode = False
        self._saved = None
        self._pending_resize = None
        self.buffer = self._blank_buffer()
        super().reset()
        self.title = ""
        self.app_cursor = False
        self.mouse_mode = 0
        self.mouse_sgr = False
        self.bracketed_paste = False
        self.focus_events = False
        self.scroll_count = 0
        self._wrapped_lines = set()
        self._in_draw = 0

    @property
    def alt_screen(self) -> bool:
        """Whether a full-screen program currently owns the display."""
        return self._alt_mode

    # -- rendering helpers ----------------------------------------------
    def cell(self, row: int, column: int) -> object:
        """Return one cell's ``Char``, including blank cells."""
        return self.buffer[row][column]

    def row_cells(self, row: int) -> list[object]:
        return [self.buffer[row][column] for column in range(self.columns)]

    def text_of_row(self, row: int) -> str:
        return "".join(self.buffer[row][column].data for column in range(self.columns))


def make_emulator(columns: int, lines: int, history: int) -> tuple[TerminalScreen, pyte.ByteStream]:
    """Create a screen plus the byte stream that feeds it."""
    screen = TerminalScreen(columns, lines, history=history)
    return screen, pyte.ByteStream(screen)
