"""Terminal emulation on top of pyte.

pyte implements the VT100/xterm command set (cursor addressing, scroll
regions, 256-colour and true-colour SGR, character sets, ...), but it has no
alternate screen, mouse reporting or application cursor keys. This module
adds those pieces so full-screen programs (vim, less, htop, tmux) behave like
they do in a real terminal.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from typing import Callable

import pyte
from pyte.screens import HistoryScreen, Margins, Screen, StaticDefaultDict


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

    # -- pyte hooks ------------------------------------------------------
    def bell(self, *args: object) -> None:
        if self.on_bell is not None:
            self.on_bell()

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
        buffer, cursor, margins, lines, columns = self._saved
        self.buffer = buffer
        self.cursor = cursor
        self.margins = margins
        self._alt_mode = False
        self._saved = None
        current_lines, current_columns = self.lines, self.columns
        if (current_lines, current_columns) != (lines, columns):
            # pyte's resize() is a no-op when the requested size equals the
            # current one, so restore the saved size first to force it.
            self.lines, self.columns = lines, columns
            super().resize(current_lines, current_columns)
        if self._pending_resize is not None:
            pending_lines, pending_columns = self._pending_resize
            self._pending_resize = None
            if (pending_lines, pending_columns) != (self.lines, self.columns):
                super().resize(pending_lines, pending_columns)

    def resize(self, lines: int | None = None, columns: int | None = None) -> None:
        lines = lines or self.lines
        columns = columns or self.columns
        if self._alt_mode:
            # The main buffer is resized when the alternate screen is left.
            self._pending_resize = (lines, columns)
        super().resize(lines, columns)

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
