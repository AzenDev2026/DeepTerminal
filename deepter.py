#!/usr/bin/env python3
"""DeepTerminal — a native Qt terminal for PowerShell, Bash and any shell.

This is the launcher. The application itself lives in the ``deepterminal``
package (PTY backend, pyte-based emulator, terminal widget, window).
"""

from __future__ import annotations

import argparse
import sys

try:
    from deepterminal.config import APP_NAME, APP_VERSION, Config, program_dir
except ImportError as error:  # PyQt6 or the package itself is missing.
    print(
        f"DeepTerminal cannot start: {error}\nRun ./install.sh to create the "
        "virtual environment and install the dependencies.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deepterminal",
        description="DeepTerminal — a native Qt terminal for PowerShell, Bash and any shell.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument(
        "--shell",
        choices=["pwsh", "bash", "custom"],
        help="Shell for the first tab (default: the saved setting)",
    )
    parser.add_argument(
        "--command",
        metavar="COMMAND",
        help='Custom shell command used with --shell custom, e.g. "fish -i"',
    )
    parser.add_argument(
        "--working-dir",
        metavar="DIR",
        help="Start directory for the first tab (default: home, or the saved setting)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args, qt_args = build_parser().parse_known_args(argv)

    try:
        import pyte  # noqa: F401
    except ImportError:
        print(
            "DeepTerminal needs the 'pyte' package. Run ./install.sh or "
            "pip install -r requirements.txt.",
            file=sys.stderr,
        )
        return 1

    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    from deepterminal.window import MainWindow

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("AzenDev")
    app.setDesktopFileName("deepterminal")
    icon_path = program_dir() / "deepterm.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    config = Config()
    if args.command:
        config.set("custom_shell", args.command)
    window = MainWindow(config=config, shell_key=args.shell, working_dir=args.working_dir)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
