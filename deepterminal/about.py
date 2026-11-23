"""In-terminal About info.

The shell-side ``DTinfo`` command prints only an invisible OSC marker
(:data:`DTINFO_MARKER`). The terminal view catches the marker and renders the
DeepTerminal icon **inside the terminal** as chafa-style coloured half-block
art (see :mod:`deepterminal.art`), with the version info beside it —
sysfetch/fastfetch layout, no floating overlay window.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess

from .art import compose, icon_art_rows
from .config import APP_NAME, APP_VERSION

#: Invisible OSC marker the shell-side ``DTinfo`` function prints. pyte
#: silently swallows unknown OSC sequences, so nothing of this reaches the
#: screen; the terminal view catches it and renders the icon image instead.
DTINFO_MARKER = b"\x1b]663;dtinfo\x07"

#: Matches the marker inside a raw PTY chunk (which may split it in half).
DTINFO_RE = re.compile(rb"\x1b\]663;dtinfo\x07")


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


def about_lines() -> list[str]:
    """The info column shown next to the icon art."""
    python_row, pyqt_row = _versions_line()
    return [
        f"{APP_NAME} {APP_VERSION} — a native Qt terminal",
        "for PowerShell 7, Bash and any shell",
        "",
        "  PowerShell Core  " + _pwsh_version(),
        "  Bash             " + _bash_version(),
        "  " + python_row,
        "  " + pyqt_row,
        "  Kernel           " + platform.release(),
        "",
        "  DTinfo for info · codeout for fun",
    ]


def about_text(icon_path=None, background: str = "#121212") -> str:
    """DTinfo output: chafa-style icon art on the left, info on the right."""
    art = icon_art_rows(icon_path, background=background) if icon_path else []
    return compose(art, about_lines()) + "\n"
