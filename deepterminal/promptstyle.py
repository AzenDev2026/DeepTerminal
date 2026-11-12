"""Styled shell prompts: presets, ANSI builders and a live preview.

DeepTerminal writes the prompt *into* the shell (``PS1`` for Bash, a
``prompt`` function for PowerShell), so the styled prompt is drawn by the
emulator exactly like normal output — truecolour, icons and all. The preview
in the settings dialog uses the same hex colours, so it is always WYSIWYG.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from .config import Config

RESET = "\x1b[0m"

#: Named colours offered by the prompt designer. Values are truecolour hex
#: strings so the preview and the terminal render the exact same colour.
COLORS: dict[str, str] = {
    "cyan": "#4cd1e0",
    "green": "#a5e075",
    "blue": "#4dc4ff",
    "magenta": "#de73ff",
    "yellow": "#ffd75f",
    "red": "#ff616e",
    "orange": "#ffaf5f",
    "purple": "#b294ff",
    "pink": "#ff9eb5",
    "white": "#ffffff",
    "gray": "#9a9a9a",
    "accent": "#4c9aff",
}

#: Order used by the colour pickers.
COLOR_ORDER = ("cyan", "green", "blue", "magenta", "yellow", "red", "orange", "purple", "pink", "white", "gray", "accent")

#: Prompt presets. ``custom`` reuses the legacy plain format string;
#: ``none`` keeps the shell's own prompt.
PRESETS: dict[str, dict[str, object]] = {
    "arrow": {"label": "Arrow", "symbol": "❯", "symbol_color": "cyan", "path_color": "blue", "user_host": False},
    "angled": {"label": "Angled", "symbol": "➜", "symbol_color": "green", "path_color": "blue", "user_host": False},
    "minimal": {"label": "Minimal", "symbol": "❯", "symbol_color": "accent", "path_color": "gray", "user_host": False},
    "whale": {"label": "Whale", "symbol": "🐳", "symbol_color": "cyan", "path_color": "blue", "user_host": False},
    "powerline": {
        "label": "Powerline",
        "symbol": "⚡",
        "symbol_color": "accent",
        "path_color": "",
        "user_host": True,
        "powerline": True,
        "user_host_fg": "#e8e8e8",
        "user_host_bg": "#3a3a3a",
        "path_fg": "#0e1116",
        "path_bg": "#4c9aff",
        "symbol_on_bg": "#ffffff",
    },
    "custom": {"label": "Custom format", "symbol": "❯", "symbol_color": "cyan", "path_color": "blue", "user_host": False},
    "none": {"label": "Shell default", "symbol": "❯", "symbol_color": "cyan", "path_color": "blue", "user_host": False},
}

#: Order used by the style picker.
STYLE_ORDER = ("arrow", "angled", "minimal", "powerline", "whale", "custom", "none")


@dataclass
class PromptStyle:
    """One fully resolved prompt look."""

    symbol: str
    symbol_hex: str
    path_hex: str
    user_host: bool
    powerline: bool = False
    user_host_fg: str = ""
    user_host_bg: str = ""
    path_fg: str = ""
    path_bg: str = ""
    symbol_on_bg: str = "#ffffff"


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def sgr(fg: str | None = None, bg: str | None = None) -> str:
    """Build a truecolour SGR sequence, or "" when nothing is requested."""
    parts: list[str] = []
    if fg:
        parts.append("38;2;" + ";".join(str(channel) for channel in hex_to_rgb(fg)))
    if bg:
        parts.append("48;2;" + ";".join(str(channel) for channel in hex_to_rgb(bg)))
    if not parts:
        return ""
    return "\x1b[" + ";".join(parts) + "m"


def build_style(
    name: str,
    symbol: str = "",
    symbol_color: str = "",
    path_color: str = "",
    user_host: bool = False,
) -> PromptStyle | None:
    """Resolve a prompt style from explicit values (no Config involved).

    Returns None for ``custom`` and ``none``, which are handled elsewhere.
    """
    key = (name or "").strip().lower()
    if key in ("", "custom", "none"):
        return None
    preset = PRESETS.get(key, PRESETS["arrow"])
    powerline = bool(preset.get("powerline"))
    chosen_symbol = (symbol or "").strip() or str(preset["symbol"])
    chosen_symbol_color = (symbol_color or "").strip() or str(preset["symbol_color"])
    chosen_path_color = (path_color or "").strip() or str(preset["path_color"]) or "blue"
    return PromptStyle(
        symbol=chosen_symbol,
        symbol_hex=COLORS.get(chosen_symbol_color, COLORS["cyan"]),
        path_hex="" if powerline else COLORS.get(chosen_path_color, COLORS["blue"]),
        user_host=bool(user_host) or bool(preset.get("user_host")),
        powerline=powerline,
        user_host_fg=str(preset.get("user_host_fg", "")),
        user_host_bg=str(preset.get("user_host_bg", "")),
        path_fg=str(preset.get("path_fg", "")),
        path_bg=str(preset.get("path_bg", "")),
        symbol_on_bg=str(preset.get("symbol_on_bg", "#ffffff")),
    )


def style_for(config: Config) -> PromptStyle | None:
    """Resolve the styled prompt from a Config, or None for shell default."""
    name = config.get_str("prompt_style")
    if name.strip().lower() in ("", "custom", "none"):
        return None
    return build_style(
        name,
        symbol=config.get_str("prompt_symbol"),
        symbol_color=config.get_str("prompt_symbol_color"),
        path_color=config.get_str("prompt_path_color"),
        user_host=config.get_bool("prompt_user_host"),
    )


def _bash_segment(sequence: str, text: str) -> str:
    """Wrap an SGR sequence in Bash's non-printing markers ``\\[`` ``\\]``."""
    return "\\[" + sequence.replace("\x1b", "\\033") + "\\]" + text


def _pwsh_escape(text: str) -> str:
    """Escape user text for a PowerShell double-quoted string."""
    return text.replace("`", "``").replace("$", "`$").replace('"', '`"')


def bash_ps1(config: Config) -> str:
    """Build the PS1 value; "" means "keep the shell's own prompt"."""
    name = config.get_str("prompt_style").strip().lower()
    if name in ("", "none"):
        return ""
    if name == "custom":
        return config.get_str("prompt").replace("{path}", r"\w")
    style = style_for(config)
    if style is None:
        return ""
    parts: list[str] = []
    if style.powerline:
        if style.user_host and style.user_host_bg:
            parts.append(_bash_segment(sgr(fg=style.user_host_fg, bg=style.user_host_bg), r" \u@\h "))
        if style.path_bg:
            parts.append(_bash_segment(sgr(fg=style.path_fg, bg=style.path_bg), r"\w "))
            parts.append(_bash_segment(sgr(fg=style.symbol_on_bg, bg=style.path_bg), style.symbol))
        else:
            parts.append(_bash_segment(sgr(fg=style.symbol_hex), style.symbol))
        parts.append(_bash_segment(RESET, " "))
    else:
        if style.user_host:
            parts.append(_bash_segment(sgr(fg=style.path_hex), r"\u@\h "))
        if style.path_hex:
            parts.append(_bash_segment(sgr(fg=style.path_hex), r"\w"))
        parts.append(" ")
        parts.append(_bash_segment(sgr(fg=style.symbol_hex), style.symbol))
        parts.append(_bash_segment(RESET, " "))
    return "".join(parts)


def pwsh_prompt_function(config: Config) -> str | None:
    """Build the PowerShell ``prompt`` function, or None for shell default.

    The returned string is a complete ``function prompt { ... }`` statement.
    """
    name = config.get_str("prompt_style").strip().lower()
    if name in ("", "none"):
        return None
    if name == "custom":
        fmt = config.get_str("prompt")
        before, marker, after = fmt.partition("{path}")
        if marker == "":
            body = _pwsh_escape(fmt)
        else:
            body = _pwsh_escape(before) + "$(Get-Location)" + _pwsh_escape(after)
        return f'function prompt {{ "{body}" }}'
    style = style_for(config)
    if style is None:
        return None
    pieces: list[str] = []
    if style.powerline:
        if style.user_host and style.user_host_bg:
            pieces.append(
                sgr(fg=style.user_host_fg, bg=style.user_host_bg)
                + " $([Environment]::UserName)@$([Environment]::MachineName) "
            )
        if style.path_bg:
            pieces.append(sgr(fg=style.path_fg, bg=style.path_bg) + "$(Get-Location) ")
            pieces.append(sgr(fg=style.symbol_on_bg, bg=style.path_bg) + _pwsh_escape(style.symbol))
        else:
            pieces.append(sgr(fg=style.symbol_hex) + _pwsh_escape(style.symbol))
        pieces.append(RESET + " ")
    else:
        if style.user_host:
            pieces.append(
                sgr(fg=style.path_hex)
                + " $([Environment]::UserName)@$([Environment]::MachineName) "
            )
        if style.path_hex:
            pieces.append(sgr(fg=style.path_hex) + "$(Get-Location)")
        pieces.append(" " + sgr(fg=style.symbol_hex) + _pwsh_escape(style.symbol) + RESET + " ")
    # The body starts with literal ESC bytes from sgr(); convert them to
    # PowerShell's canonical `` `e `` escape so no raw control characters
    # travel in the -Command argument.
    return 'function prompt { "' + "".join(pieces).replace("\x1b", "`e") + '" }'


def bash_prompt_command(config: Config) -> str | None:
    """The command written to Bash right after startup, or None."""
    ps1 = bash_ps1(config)
    if ps1 == "":
        return None
    return "PS1=" + "'" + ps1.replace("'", "'\\''") + "'" + "\n"


def preview_html(
    name: str,
    symbol: str = "",
    symbol_color: str = "",
    path_color: str = "",
    user_host: bool = False,
    custom_format: str = "",
) -> str:
    """Small HTML preview of a prompt for the settings dialog."""
    key = (name or "").strip().lower()
    if key in ("", "none"):
        return '<span style="color:#8a8a8a">shell&rsquo;s default prompt</span>'
    if key == "custom":
        text = (custom_format or "").replace("{path}", "~/projects")
        return html.escape(text) or "&nbsp;"
    style = build_style(key, symbol, symbol_color, path_color, user_host)
    if style is None:
        return "&nbsp;"
    path = "~/projects"
    bits: list[str] = []
    if style.powerline:
        if style.user_host and style.user_host_bg:
            bits.append(
                f'<span style="background:{style.user_host_bg};color:{style.user_host_fg};'
                f'border-radius:4px 0 0 4px;">&nbsp;user@host&nbsp;</span>'
            )
        if style.path_bg:
            bits.append(f'<span style="background:{style.path_bg};color:{style.path_fg};">&nbsp;{path}&nbsp;</span>')
            bits.append(
                f'<span style="background:{style.path_bg};color:{style.symbol_on_bg};'
                f'border-radius:0 4px 4px 0;">{html.escape(style.symbol)}&nbsp;</span>'
            )
        else:
            bits.append(f'<span style="color:{style.symbol_hex}">{html.escape(style.symbol)}</span>')
        return "".join(bits)
    if user_host:
        bits.append(f'<span style="color:{style.path_hex}">user@host&nbsp;</span>')
    if style.path_hex:
        bits.append(f'<span style="color:{style.path_hex}">{path}</span>')
    bits.append(f' <span style="color:{style.symbol_hex}">{html.escape(style.symbol)}</span>')
    return "".join(bits)
