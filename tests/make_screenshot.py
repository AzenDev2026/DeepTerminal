#!/usr/bin/env python3
"""Render DeepTerminal's main window offscreen and save a screenshot.

Run with:  python tests/make_screenshot.py [output.png]
Used to regenerate docs/screenshot.png after UI changes.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from deepterminal.config import Config  # noqa: E402
from deepterminal.window import MainWindow  # noqa: E402


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "docs" / "screenshot.png"
    app = QApplication(sys.argv[:1])
    with tempfile.TemporaryDirectory() as directory:
        config = Config(QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat))
        config.set("shell", "bash")
        config.set("font_size", 11)
        config.set("prompt_style", "arrow")
        config.sync()
        window = MainWindow(config=config)
        window.resize(1080, 680)
        window.show()
        window.new_tab("bash")
        window.tabs.setTabText(0, "bash")
        window.tabs.setTabText(1, "python")

        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            app.processEvents()
            view = window.tabs.currentWidget()
            if view is not None and "❯" in view.screen_text():
                break
            time.sleep(0.05)

        view = window.tabs.currentWidget()
        if view is not None:
            view._write_input(b"ls /usr/share/pixmaps\r")
            for _ in range(40):
                app.processEvents()
                time.sleep(0.05)
        app.processEvents()
        window.tabs.setCurrentIndex(0)
        app.processEvents()
        view = window.tabs.currentWidget()
        if view is not None:
            view._write_input(b"echo 'hello from the other tab' && sleep 0.3\r")
            for _ in range(40):
                app.processEvents()
                time.sleep(0.05)

        output.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(output))
        window.close()
        app.processEvents()
    print(f"saved {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
