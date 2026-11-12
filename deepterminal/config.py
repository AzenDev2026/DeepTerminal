"""Configuration, themes and small shared helpers for DeepTerminal."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QSettings

ORG = "AzenDev"
APP = "DeepTerminal"
APP_NAME = "DeepTerminal"
APP_VERSION = "2.1.0"

#: Selectable default shells. "custom" means the command in ``custom_shell``.
SHELL_CHOICES = ("pwsh", "bash", "custom")

DEFAULTS: dict[str, object] = {
    # Kept from beta 1 so existing settings keep working.
    "prompt": "DT ({path})::: ",
    "theme": "dark",
    "startup_cmd": "",
    # New in beta 2.
    "shell": "pwsh",
    "custom_shell": "",
    "font_family": "",
    "font_size": 11,
    "scrollback": 5000,
    "cursor_blink": True,
    "working_dir": "",
    # New in 2.1: styled prompts (see promptstyle.py). ``prompt`` keeps its
    # beta meaning and is only used when prompt_style is "custom".
    "prompt_style": "arrow",
    "prompt_symbol": "",
    "prompt_symbol_color": "",
    "prompt_path_color": "",
    "prompt_user_host": False,
}

#: Terminal palettes. Colours map the 16 ANSI names pyte produces; values are
#: CSS hex strings. ``default`` is resolved from ``fg``/``bg``.
THEMES: dict[str, dict[str, object]] = {
    "dark": {
        "window_bg": "#1b1b1b",
        "bg": "#121212",
        "fg": "#d6d6d6",
        "cursor": "#f5f5f5",
        "cursor_text": "#121212",
        "selection": "#264f78",
        "selection_text": "#ffffff",
        "border": "#2d2d2d",
        "tab_bg": "#1b1b1b",
        "tab_active_bg": "#121212",
        "tab_fg": "#8a8a8a",
        "tab_active_fg": "#ffffff",
        "accent": "#4c9aff",
        "palette": {
            "black": "#2e2e2e",
            "red": "#e05561",
            "green": "#8cc265",
            "brown": "#d18f52",
            "blue": "#4aa5f0",
            "magenta": "#c162de",
            "cyan": "#42b3c2",
            "white": "#d6d6d6",
            "brightblack": "#6b6b6b",
            "brightred": "#ff616e",
            "brightgreen": "#a5e075",
            "brightbrown": "#f0a45d",
            "brightblue": "#4dc4ff",
            "brightmagenta": "#de73ff",
            "brightcyan": "#4cd1e0",
            "brightwhite": "#ffffff",
        },
    },
    "light": {
        "window_bg": "#ececec",
        "bg": "#ffffff",
        "fg": "#1f2328",
        "cursor": "#1f2328",
        "cursor_text": "#ffffff",
        "selection": "#b6d7ff",
        "selection_text": "#0b1f33",
        "border": "#d0d0d0",
        "tab_bg": "#ececec",
        "tab_active_bg": "#ffffff",
        "tab_fg": "#595959",
        "tab_active_fg": "#000000",
        "accent": "#005a9e",
        "palette": {
            "black": "#24292f",
            "red": "#cf222e",
            "green": "#116329",
            "brown": "#953800",
            "blue": "#0969da",
            "magenta": "#8250df",
            "cyan": "#1b7c83",
            "white": "#6e7781",
            "brightblack": "#57606a",
            "brightred": "#a40e26",
            "brightgreen": "#1a7f37",
            "brightbrown": "#9a6700",
            "brightblue": "#218bff",
            "brightmagenta": "#a475f9",
            "brightcyan": "#3192aa",
            "brightwhite": "#8c959f",
        },
    },
}


def theme_names() -> list[str]:
    """Return the selectable theme identifiers."""
    return list(THEMES)


def get_theme(name: str) -> dict[str, object]:
    """Return one theme, falling back to dark for unknown names."""
    return THEMES.get(name, THEMES["dark"])


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _as_str(value: object, default: str) -> str:
    return default if value is None else str(value)


class Config:
    """Typed wrapper around the QSettings store shared with beta 1."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self.settings = settings if settings is not None else QSettings(ORG, APP)

    # -- typed accessors -------------------------------------------------
    def get_str(self, key: str) -> str:
        default = str(DEFAULTS[key])
        return _as_str(self.settings.value(key, default), default)

    def get_int(self, key: str) -> int:
        default = int(DEFAULTS[key])  # type: ignore[arg-type]
        limits = {
            "font_size": (6, 32),
            "scrollback": (500, 100_000),
        }
        minimum, maximum = limits.get(key, (0, 1_000_000))
        return _as_int(self.settings.value(key, default), default, minimum, maximum)

    def get_bool(self, key: str) -> bool:
        default = bool(DEFAULTS[key])
        return _as_bool(self.settings.value(key, default), default)

    def get(self, key: str) -> object:
        return self.settings.value(key, DEFAULTS.get(key))

    def set(self, key: str, value: object) -> None:
        self.settings.setValue(key, value)

    def apply(self, values: dict[str, object]) -> None:
        for key, value in values.items():
            self.set(key, value)

    def sync(self) -> None:
        self.settings.sync()

    # -- derived values --------------------------------------------------
    def theme(self) -> dict[str, object]:
        return get_theme(self.get_str("theme"))

    def working_dir(self) -> str:
        """Expand the configured start directory, defaulting to the home dir."""
        raw = self.get_str("working_dir").strip()
        if raw == "":
            return os.path.expanduser("~")
        return os.path.abspath(os.path.expanduser(raw))

    def geometry(self) -> bytes | None:
        value = self.settings.value("geometry")
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        return None

    def save_geometry(self, data: bytes) -> None:
        self.set("geometry", data)


def default_font_family() -> str:
    """Pick a sensible monospace family for the current system."""
    from PyQt6.QtGui import QFontDatabase

    configured = QSettings(ORG, APP).value("font_family", "")
    if isinstance(configured, str) and configured.strip() != "":
        return configured.strip()
    system = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    return system.family() or "Monospace"


def program_dir() -> Path:
    """Directory holding the launcher and ``deepterm.png``."""
    return Path(__file__).resolve().parent.parent
