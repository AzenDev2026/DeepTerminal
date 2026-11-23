"""Shell profiles: choose the program that runs inside a terminal tab."""

from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass

from .codeout import bash_codeout_setup, pwsh_codeout_setup
from .config import APP_VERSION, Config
from .promptstyle import bash_prompt_command, pwsh_prompt_function


class ShellError(Exception):
    """Raised when the configured shell cannot be resolved."""


@dataclass(frozen=True)
class ShellProfile:
    """One resolved shell invocation."""

    key: str
    label: str
    argv: tuple[str, ...]
    #: Text written to the shell right after it starts (bash prompt setup).
    prompt_command: str | None = None
    #: Start the PTY with input echo disabled; prompt_command turns it back
    #: on, so the injected setup is never echoed to the screen.
    echo_off: bool = False

    def title(self) -> str:
        return self.label


def _bash_dtinfo_setup() -> str:
    """Bash command defining DTinfo() — prints only the invisible OSC marker;
    the terminal view catches it and shows the icon image + info client-side."""
    return "DTinfo() { printf '\\033]663;dtinfo\\007'; }"


def _pwsh_dtinfo_setup() -> str:
    """PowerShell function DTinfo printing the invisible OSC marker."""
    return 'function DTinfo { Write-Host -NoNewline "$([char]27)]663;dtinfo$([char]7)" }'


def pwsh_profile(config: Config) -> ShellProfile:
    executable = shutil.which("pwsh")
    if executable is None:
        raise ShellError(
            "PowerShell 7 (pwsh) was not found on PATH. Install it or pick another shell in Settings."
        )
    prompt_function = pwsh_prompt_function(config)
    parts = [
        prompt_function,
        _pwsh_dtinfo_setup(),
        pwsh_codeout_setup(),
        "$env:PAGER = 'cat'",
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
        "$OutputEncoding = [System.Text.Encoding]::UTF8",
    ]
    if config.get_bool("auto_clear"):
        parts.append("Clear-Host")
    # Print the About banner, then let the shell show its first prompt.
    parts.append("DTinfo")
    init = "; ".join(part for part in parts if part)
    argv = (executable, "-NoLogo", "-NoExit", "-Command", init)
    return ShellProfile(key="pwsh", label="PowerShell 7", argv=argv)


def bash_profile(config: Config) -> ShellProfile:
    executable = shutil.which("bash")
    if executable is None:
        raise ShellError("bash was not found on PATH. Install it or pick another shell in Settings.")
    setup = bash_prompt_command(config)
    if setup:
        # Run the PS1 setup, define DTinfo and re-enable echo as a single
        # command so bash prints its prompt only once instead of once per line.
        setup = setup.rstrip("\n") + "; "
    setup += _bash_dtinfo_setup() + "; " + bash_codeout_setup() + "; stty echo"
    if config.get_bool("auto_clear"):
        # Clear the screen automatically on open (fall back to raw ANSI if
        # `clear` is not installed), then show the About banner.
        setup += "; command -v clear >/dev/null 2>&1 && clear || printf '\\033[2J\\033[H'"
    setup += "; DTinfo\n"
    return ShellProfile(
        key="bash",
        label="Bash",
        argv=(executable, "-i"),
        prompt_command=setup,
        echo_off=True,
    )


def custom_profile(command: str) -> ShellProfile:
    text = command.strip()
    if text == "":
        raise ShellError("Set a custom shell command in Settings first (for example: fish -i).")
    try:
        argv = tuple(shlex.split(text))
    except ValueError as error:
        raise ShellError(f"The custom shell command is not valid: {error}") from error
    if not argv:
        raise ShellError("The custom shell command is empty.")
    executable = shutil.which(argv[0])
    if executable is None:
        raise ShellError(f"Command not found: {argv[0]}")
    label = os.path.basename(argv[0]) or argv[0]
    return ShellProfile(key="custom", label=label, argv=(executable, *argv[1:]))


def resolve_profile(config: Config, shell_key: str | None = None) -> ShellProfile:
    """Resolve the configured (or explicitly requested) shell profile."""
    key = (shell_key or config.get_str("shell")).strip().lower()
    if key == "bash":
        return bash_profile(config)
    if key == "custom":
        return custom_profile(config.get_str("custom_shell"))
    return pwsh_profile(config)


def shell_choices() -> list[tuple[str, str, str]]:
    """Return ``(key, label, availability detail)`` for the settings dialog."""
    choices: list[tuple[str, str, str]] = []
    pwsh_path = shutil.which("pwsh")
    choices.append(("pwsh", "PowerShell 7", pwsh_path or "not found on PATH"))
    bash_path = shutil.which("bash")
    choices.append(("bash", "Bash", bash_path or "not found on PATH"))
    choices.append(("custom", "Custom command", "any executable you set below"))
    return choices


def build_environment() -> dict[str, str]:
    """Environment for a shell: UTF-8, 256 colours, terminal identity."""
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["TERM_PROGRAM"] = "DeepTerminal"
    env["TERM_PROGRAM_VERSION"] = APP_VERSION
    # Colour-suppressing hints inherited from the launcher are poison for a
    # truecolour terminal: PowerShell (7.2+) switches $PSStyle.OutputRendering
    # to PlainText when NO_COLOR is set and silently strips every ANSI
    # sequence from the prompt — styled prompts then render colourless.
    # The terminal itself decides about colour, so drop the hints here.
    for name in ("NO_COLOR", "CLICOLOR"):
        env.pop(name, None)
    lang = env.get("LANG", "")
    if not lang.upper().endswith(("UTF-8", "UTF8")):
        env["LANG"] = "C.UTF-8"
    env.setdefault("LC_CTYPE", env["LANG"])
    return env
