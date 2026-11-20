"""In-terminal About info.

Rendered as a character box shown at the top of every new tab and by the
``DTinfo`` command typed inside Bash / PowerShell tabs.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess

from .config import APP_NAME, APP_VERSION

_WIDTH = 52
_INNER = _WIDTH - 4


def _shell_version(command: str, args: tuple[str, ...], pattern: str) -> str:
    executable = shutil.which(command)
    if executable is None:
        return "not found"
    try:
        out = subprocess.run(
            [executable, *args], capture_output=True, text=True, timeout=10
        ).stdout
        match = re.search(pattern, out)
        if match:
            return match.group(1)
        first = out.splitlines()[0].strip() if out.strip() else ""
        return first or "unknown"
    except Exception:
        return "not found"


def _pwsh_version() -> str:
    return _shell_version("pwsh", ("--version",), r"([0-9]+(?:\.[0-9]+)+)")


def _bash_version() -> str:
    return _shell_version("bash", ("--version",), r"GNU bash, version ([0-9]+(?:\.[0-9]+)+)")


def _pyte_version() -> str:
    try:
        from importlib.metadata import version

        return version("pyte")
    except Exception:
        return "unknown"


def _versions_line() -> str:
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
    except Exception:  # pragma: no cover - defensive
        QT_VERSION_STR = PYQT_VERSION_STR = "?"
    python_v = platform.python_version()
    return (
        f"Python {python_v} · Qt {QT_VERSION_STR}",
        f"PyQt {PYQT_VERSION_STR} · pyte {_pyte_version()}",
    )


def _box(lines: list[str]) -> str:
    top = "╭" + "─" * (_WIDTH - 2) + "╮"
    bottom = "╰" + "─" * (_WIDTH - 2) + "╯"

    def row(text: str) -> str:
        if len(text) > _INNER:
            text = text[:_INNER]
        return "│ " + text.ljust(_INNER) + " │"

    return "\n".join([top] + [row(line) for line in lines] + [bottom])


def about_text() -> str:
    """Character-boxed About block shown in the terminal."""
    python_row, pyqt_row = _versions_line()
    lines = [
        "",
        "  ██████╗ ████████╗      " + f"{APP_NAME} {APP_VERSION}",
        "  ██╔══██╗╚══██╔══╝      ──────────────────────",
        "  ██║  ██║   ██║         A native Qt terminal",
        "  ██║  ██║   ██║         for PowerShell 7, Bash",
        "  ██████╔╝   ██║         and any shell",
        "  ╚═════╝    ╚═╝",
        "",
        "  PowerShell Core  " + _pwsh_version(),
        "  Bash             " + _bash_version(),
        "  " + python_row,
        "  " + pyqt_row,
        "",
        "  Type DTinfo to see this again",
    ]
    return _box(lines) + "\n"
