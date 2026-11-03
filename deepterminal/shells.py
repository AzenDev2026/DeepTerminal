"""Shell profiles: choose the program that runs inside a terminal tab."""

from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass

from .config import APP_VERSION, Config


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

    def title(self) -> str:
        return self.label


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def pwsh_prompt_function(fmt: str) -> str:
    """Build a PowerShell ``prompt`` function for ``fmt`` (``{path}`` = cwd)."""
    before, marker, after = fmt.partition("{path}")
    if marker == "":
        body = _ps_quote(fmt)
    else:
        body = f"{_ps_quote(before)} + $(Get-Location) + {_ps_quote(after)}"
    return f"function prompt {{ {body} }}"


def pwsh_profile(prompt_format: str) -> ShellProfile:
    executable = shutil.which("pwsh")
    if executable is None:
        raise ShellError(
            "PowerShell 7 (pwsh) was not found on PATH. Install it or pick another shell in Settings."
        )
    argv: tuple[str, ...]
    fmt = prompt_format if prompt_format.strip() != "" else ""
    if fmt == "":
        argv = (executable, "-NoLogo")
    else:
        init = "; ".join(
            [
                pwsh_prompt_function(fmt),
                "$env:PAGER = 'cat'",
                "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
                "$OutputEncoding = [System.Text.Encoding]::UTF8",
            ]
        )
        argv = (executable, "-NoLogo", "-NoExit", "-Command", init)
    return ShellProfile(key="pwsh", label="PowerShell 7", argv=argv)


def bash_profile(prompt_format: str) -> ShellProfile:
    executable = shutil.which("bash")
    if executable is None:
        raise ShellError("bash was not found on PATH. Install it or pick another shell in Settings.")
    prompt_command = None
    if prompt_format.strip() != "":
        value = prompt_format.replace("{path}", r"\w")
        prompt_command = f"PS1={_sh_quote(value)}\n"
    return ShellProfile(key="bash", label="Bash", argv=(executable, "-i"), prompt_command=prompt_command)


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
    prompt = config.get_str("prompt")
    if key == "bash":
        return bash_profile(prompt)
    if key == "custom":
        return custom_profile(config.get_str("custom_shell"))
    return pwsh_profile(prompt)


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
    lang = env.get("LANG", "")
    if not lang.upper().endswith(("UTF-8", "UTF8")):
        env["LANG"] = "C.UTF-8"
    env.setdefault("LC_CTYPE", env["LANG"])
    return env
