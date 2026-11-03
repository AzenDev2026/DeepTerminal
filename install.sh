#!/usr/bin/env bash
# DeepTerminal installer. Usage: ./install.sh [--uninstall]
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
ICON_DIR="$DATA_HOME/icons"
DESKTOP_DIR="$DATA_HOME/applications"
APP_ID="deepterminal"

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$DESKTOP_DIR/$APP_ID.desktop" "$ICON_DIR/$APP_ID.png"
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    echo "Removed the DeepTerminal launcher and icon."
    echo "The checkout and $VENV were left in place; delete them manually if you want."
    exit 0
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    sed -n '2,3p' "$0"
    exit 0
fi

export PIP_DISABLE_PIP_VERSION_CHECK=1

echo "==> DeepTerminal installer"
if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 is required." >&2
    exit 1
fi
if ! python3 -c 'import venv' >/dev/null 2>&1; then
    echo "error: python3-venv is required (on Arch: pacman -S python; on Debian: apt install python3-venv)." >&2
    exit 1
fi

echo "==> Python environment"
if [[ ! -d "$VENV" ]]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install -r "$DIR/requirements.txt"

echo "==> Desktop integration"
mkdir -p "$ICON_DIR" "$DESKTOP_DIR"
if [[ -f "$DIR/deepterm.png" ]]; then
    cp "$DIR/deepterm.png" "$ICON_DIR/$APP_ID.png"
else
    echo "warning: deepterm.png not found; the launcher will use a generic icon." >&2
fi

cat > "$DESKTOP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Version=1.1
Type=Application
Name=DeepTerminal
GenericName=Terminal
Comment=Native terminal for PowerShell 7, Bash and any shell
Exec="$VENV/bin/python" "$DIR/deepter.py"
Path=$DIR
Icon=$ICON_DIR/$APP_ID.png
Terminal=false
Categories=System;TerminalEmulator;
Keywords=terminal;shell;console;pwsh;bash;pty;
StartupNotify=true
StartupWMClass=DeepTerminal
EOF
chmod +x "$DESKTOP_DIR/$APP_ID.desktop"
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "$ICON_DIR" 2>/dev/null || true
fi

echo "==> Checking shells"
for shell in pwsh bash; do
    if command -v "$shell" >/dev/null 2>&1; then
        printf '    %-5s %s\n' "$shell" "$(command -v "$shell")"
    else
        printf '    %-5s not found (select another shell in Settings)\n' "$shell"
    fi
done

echo "==> Done."
echo "    Launch 'DeepTerminal' from the application menu, or run:"
echo "    $VENV/bin/python $DIR/deepter.py"
