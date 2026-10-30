#!/bin/bash

# 获取当前脚本所在的绝对路径（不管在哪运行都能找到）
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="$DIR/.venv"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons"

echo "==> Installing DeepTerminal beta..."

# 1. 创建并激活虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "Installing dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$DIR/requirements.txt"

# 2. 处理图标
mkdir -p "$ICON_DIR"
# 如果仓库里有 deepterm.png，则复制过去。没有就生成个占位符防止报错。
if [ -f "$DIR/deepterm.png" ]; then
    cp "$DIR/deepterm.png" "$ICON_DIR/deepterminal.png"
else
    echo "Warning: deepterm.png not found. Using default icon."
    # 创建一个空白图标防止报错
    touch "$ICON_DIR/deepterminal.png"
fi

# 3. 生成 .desktop 文件
mkdir -p "$DESKTOP_DIR"
DESKTOP_FILE="$DESKTOP_DIR/deepterminal.desktop"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=DeepTerminal beta
Comment=A modern terminal frontend for PowerShell
Exec=$VENV_DIR/bin/python $DIR/deepter.py
Path=$DIR
Icon=$ICON_DIR/deepterminal.png
Terminal=false
Categories=System;TerminalEmulator;
StartupNotify=true
EOF

chmod +x "$DESKTOP_FILE"
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo "==> Installation complete!"
echo "You can now launch 'DeepTerminal beta' from your application menu."
echo "Or run this directly: $VENV_DIR/bin/python $DIR/deepter.py"