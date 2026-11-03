#!/usr/bin/env python3
"""Headless smoke tests for DeepTerminal's terminal core.

Run with:  python tests/smoke_test.py
Uses Qt's offscreen platform, so no display is required.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import QEvent, QSettings, Qt  # noqa: E402
from PyQt6.QtGui import QGuiApplication, QInputMethodEvent, QKeyEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QTabBar  # noqa: E402

from deepterminal.config import Config  # noqa: E402
from deepterminal.emulator import make_emulator  # noqa: E402
from deepterminal.shells import ShellError, bash_profile, resolve_profile  # noqa: E402
from deepterminal.window import MainWindow  # noqa: E402
from deepterminal.view import TerminalView, encode_key  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}" + (f"\n      {detail}" if detail else ""))
        FAILURES.append(name)


def wait_until(app: QApplication, predicate, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def key_event(key, modifiers=Qt.KeyboardModifier.NoModifier, text: str = "") -> QKeyEvent:
    return QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)


def test_emulator() -> None:
    screen, stream = make_emulator(20, 4, 100)
    stream.feed(b"main\r\n")
    stream.feed(b"\x1b[?1049h\x1b[H\x1b[2JALT")
    check("alt screen hides main content", screen.text_of_row(0).startswith("ALT"), screen.text_of_row(0))
    stream.feed(b"\x1b[?1049l")
    check("alt screen restores main content", "main" in screen.text_of_row(0), screen.text_of_row(0))

    screen.reset()
    screen, stream = make_emulator(20, 4, 100)
    stream.feed(b"\x1b]0;My Title\x07hello")
    check("OSC title is parsed", screen.title == "My Title", screen.title)
    check("OSC title does not leak into the screen", screen.text_of_row(0).startswith("hello"), screen.text_of_row(0))

    screen, stream = make_emulator(20, 4, 100)
    stream.feed(b"\x1b[38;2;18;52;86mX\x1b[0m\x1b[38;5;196mY\x1b[0m\x1b[1;31mZ")
    check("truecolour is parsed", screen.buffer[0][0].fg == "123456", str(screen.buffer[0][0]))
    check("256-colour is parsed", screen.buffer[0][1].fg == "ff0000", str(screen.buffer[0][1]))
    check("bold+base colour is kept", screen.buffer[0][2].fg == "red" and screen.buffer[0][2].bold)

    screen, stream = make_emulator(20, 3, 100)
    for index in range(10):
        stream.feed(f"line{index}\r\n".encode())
    check("scrollback keeps scrolled lines", len(screen.history.top) == 8, str(len(screen.history.top)))

    screen, stream = make_emulator(20, 4, 100)
    screen.set_mode(1000, private=True)
    screen.set_mode(1006, private=True)
    screen.set_mode(2004, private=True)
    screen.set_mode(1, private=True)
    check("mouse mode tracked", screen.mouse_mode == 1000 and screen.mouse_sgr)
    check("bracketed paste tracked", screen.bracketed_paste)
    check("application cursor keys tracked", screen.app_cursor)
    screen.reset_mode(1000, private=True)
    screen.reset_mode(2004, private=True)
    screen.reset_mode(1, private=True)
    check("modes reset", screen.mouse_mode == 0 and not screen.bracketed_paste and not screen.app_cursor)


def test_key_encoding() -> None:
    check("arrow (normal)", encode_key(key_event(Qt.Key.Key_Up), False) == b"\x1b[A")
    check("arrow (application)", encode_key(key_event(Qt.Key.Key_Up), True) == b"\x1bOA")
    check("ctrl+c", encode_key(key_event(Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier), False) == b"\x03")
    check("alt+x", encode_key(key_event(Qt.Key.Key_X, Qt.KeyboardModifier.AltModifier, "x"), False) == b"\x1bx")
    check("shift+tab", encode_key(key_event(Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier), False) == b"\x1b[Z")
    check("f5", encode_key(key_event(Qt.Key.Key_F5), False) == b"\x1b[15~")
    check("delete", encode_key(key_event(Qt.Key.Key_Delete), False) == b"\x1b[3~")
    check("home (application)", encode_key(key_event(Qt.Key.Key_Home), True) == b"\x1bOH")
    check(
        "ctrl+right uses a modifier sequence",
        encode_key(key_event(Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier), False) == b"\x1b[1;5C",
    )


def test_pty(app: QApplication) -> None:
    if not Path("/bin/bash").exists():
        check("bash available", False, "bash is required for this test")
        return
    with tempfile.TemporaryDirectory() as directory:
        settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
        config = Config(settings)
        config.set("theme", "dark")
        config.set("font_size", 10)
        config.set("scrollback", 2000)
        config.sync()

        view = TerminalView(config, bash_profile("DT ({path})::: "))
        view.resize(900, 560)
        view.show()

        check("shell prompt appears", wait_until(app, lambda: "DT (" in view.screen_text(), 10), view.screen_text())
        view._write_input(b"printf 'smoke-ok\\n'\r")
        check("command output appears", wait_until(app, lambda: "smoke-ok" in view.screen_text()), view.screen_text())
        view._write_input(b"if [ -t 1 ]; then echo tty-yes; else echo tty-no; fi\r")
        check("stdout is a terminal", wait_until(app, lambda: "tty-yes" in view.screen_text()), view.screen_text())

        rows, columns = view.emulator.lines, view.emulator.columns
        view._write_input(b"stty size\r")
        expected = f"{rows} {columns}"
        check("window size reaches the shell", wait_until(app, lambda: expected in view.screen_text()), view.screen_text())

        view.resize(700, 420)
        wait_until(app, lambda: (view.emulator.lines, view.emulator.columns) != (rows, columns), 3)
        new_rows, new_columns = view.emulator.lines, view.emulator.columns
        view._write_input(b"stty size\r")
        check(
            "resize reaches the shell",
            wait_until(app, lambda: f"{new_rows} {new_columns}" in view.screen_text(), 5),
            view.screen_text(),
        )

        script = Path(directory) / "alt.sh"
        script.write_text(
            "#!/bin/sh\n"
            "printf '\\033[?1049h\\033[2JALT-MARK'\n"
            "sleep 0.7\n"
            "printf '\\033[?1049l'\n"
        )
        script.chmod(0o755)
        view._write_input(f"sh {script}\r".encode())
        check(
            "alternate screen shows full-screen content",
            wait_until(app, lambda: "ALT-MARK" in view.screen_text(), 4),
            view.screen_text(),
        )
        check(
            "alternate screen restores the shell view",
            wait_until(app, lambda: "ALT-MARK" not in view.screen_text(), 6),
            view.screen_text(),
        )

        view._write_input(b"echo $TERM; echo $COLORTERM\r")
        check(
            "shell sees a 256-colour terminal",
            wait_until(app, lambda: "xterm-256color" in view.screen_text() and "truecolor" in view.screen_text(), 3),
            view.screen_text(),
        )

        view.shutdown()
        view.close()
        app.processEvents()


def test_view_extras(app: QApplication) -> None:
    with tempfile.TemporaryDirectory() as directory:
        config = Config(QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat))
        config.set("font_size", 10)
        config.set("scrollback", 5000)
        config.sync()
        view = TerminalView(config, bash_profile("DT ({path})::: "))
        view.resize(900, 560)
        view.show()
        check("view starts a shell", wait_until(app, lambda: "DT (" in view.screen_text(), 10), view.screen_text())

        ime = QInputMethodEvent("", [])
        ime.setCommitString("echo ime-ok\r")
        view.inputMethodEvent(ime)
        check("IME commit reaches the shell", wait_until(app, lambda: "ime-ok" in view.screen_text()), view.screen_text())

        view._write_input(b"sleep 30\r")
        wait_until(app, lambda: "sleep 30" in view.screen_text(), 3)
        view._write_input(b"\x03")
        wait_until(app, lambda: False, 0.2)
        view._write_input(b"echo after-int\r")
        check("Ctrl+C interrupts the foreground job", wait_until(app, lambda: "after-int" in view.screen_text(), 5), view.screen_text())

        view._write_input(b"seq 1 200\r")
        check("long output arrives", wait_until(app, lambda: "200" in view.screen_text()), view.screen_text())
        view._scroll_by(5)
        check("scrollback moves away from the bottom", view._scroll_offset > 0, str(view._scroll_offset))
        view._scroll_by(-99999)
        check("scrollback returns to the bottom", view._scroll_offset == 0, str(view._scroll_offset))

        view.select_all()
        text = view.selection_text()
        check("selection covers scrollback", "ime-ok" in text and len(text) > 500, str(len(text)))
        view.copy_selection()
        check("copy puts selection on the clipboard", "ime-ok" in QGuiApplication.clipboard().text())

        view._write_input(b"echo find-me-token\r")
        wait_until(app, lambda: "find-me-token" in view.screen_text(), 3)
        count = view.set_search("find-me-token")
        check("search finds output", count >= 2, str(count))
        check("search selects a match", view.search_position() == 0)
        view.search_step(1)
        check("search steps between matches", view.search_position() == 1)
        view.clear_search()
        check("search can be cleared", view.search_matches() == [])

        class FakePty:
            def __init__(self):
                self.written = []

            def write(self, data):
                self.written.append(data)

            def resize(self, rows, columns):
                pass

        real_pty = view.pty
        fake = FakePty()
        view.pty = fake
        view.emulator.set_mode(1000, private=True)
        view.emulator.set_mode(1006, private=True)
        view._mouse_command(0, 4, 0, True)
        check(
            "SGR mouse report uses screen coordinates",
            fake.written[-1] == b"\x1b[<0;5;" + str(view.emulator.lines).encode() + b"M",
            repr(fake.written[-1]),
        )
        view.pty = real_pty
        view.emulator.reset_mode(1000, private=True)
        view.emulator.reset_mode(1006, private=True)

        before = config.get_int("font_size")
        view.zoom(1)
        check("zoom changes the font size", config.get_int("font_size") == before + 1, str(config.get_int("font_size")))
        view.zoom(0)
        check("Ctrl+0 resets the font size", config.get_int("font_size") == 11, str(config.get_int("font_size")))

        view.resize(700, 400)
        app.processEvents()
        view._write_input(b"stty size\r")
        expected = f"{view.emulator.lines} {view.emulator.columns}"
        check("resize keeps the PTY in sync", wait_until(app, lambda: expected in view.screen_text(), 5), view.screen_text())

        view.shutdown()
        view.close()
        app.processEvents()

        try:
            resolve_profile(config, "custom")
        except ShellError:
            custom_ok = True
        else:
            custom_ok = False
        check("empty custom shell is rejected", custom_ok)

        config.set("custom_shell", "bash --norc -i")
        profile = resolve_profile(config, "custom")
        check("custom shell resolves", profile.key == "custom" and profile.argv[0].endswith("bash"), str(profile.argv))
        custom_view = TerminalView(config, profile)
        custom_view.resize(700, 400)
        custom_view.show()
        custom_view._write_input(b"echo custom-ok\r")
        check("custom shell runs", wait_until(app, lambda: "custom-ok" in custom_view.screen_text(), 8), custom_view.screen_text())
        custom_view.shutdown()
        custom_view.close()
        app.processEvents()


def test_window(app: QApplication) -> None:
    with tempfile.TemporaryDirectory() as directory:
        config = Config(QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat))
        config.set("font_size", 10)
        config.set("shell", "bash")
        config.sync()
        window = MainWindow(config=config)
        window.resize(900, 560)
        window.show()
        check("window opens one tab", window.tabs.count() == 1, str(window.tabs.count()))
        window.new_tab("bash")
        check("new tab is added", window.tabs.count() == 2, str(window.tabs.count()))
        button = window.tabs.tabBar().tabButton(1, QTabBar.ButtonPosition.RightSide)
        check("tab has a close button", button is not None)
        if button is not None:
            button.click()
            app.processEvents()
        check("close button closes the tab", window.tabs.count() == 1, str(window.tabs.count()))
        window.close()
        app.processEvents()


def main() -> int:
    app = QApplication(sys.argv[:1])
    test_emulator()
    test_key_encoding()
    test_pty(app)
    test_view_extras(app)
    test_window(app)
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s): {', '.join(FAILURES)}")
        return 1
    print("\nAll terminal checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
