import sys
import os
import re
import platform
import subprocess

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QPlainTextEdit, QLineEdit, QTabWidget, QPushButton, QLabel, 
    QInputDialog, QTabBar, QDialog, QFormLayout, QComboBox, QDialogButtonBox
)
from PyQt6.QtCore import QProcess, Qt, QSettings
from PyQt6.QtGui import QFont, QShortcut, QKeySequence, QIcon, QTextCursor, QTextCharFormat, QColor

APP_TITLE = "DeepTerminal beta"
APP_VERSION = "1.0.0"

# 正则匹配
ANSI_CONTROL_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')
ANSI_COLOR_RE = re.compile(r'\x1b\[([0-9;]+)m')

ANSI_COLORS = {
    30: "#000000", 31: "#cd3131", 32: "#0dbc79", 33: "#e5e510",
    34: "#2472c8", 35: "#bc3fbc", 36: "#11a8cd", 37: "#e5e5e5",
    90: "#666666", 91: "#f14c4c", 92: "#23d18b", 93: "#f5f543",
    94: "#3b8eea", 95: "#d670d6", 96: "#29b8db", 97: "#ffffff"
}

# ---------------- 样式表定义 ----------------
THEMES = {
    "dark": {
        "main_bg": "#1e1e1e",
        "output_bg": "#141414",
        "text_color": "#d4d4d4",
        "tab_bg": "#1e1e1e",
        "tab_selected_bg": "#141414",
        "tab_text": "#858585",
        "tab_selected_text": "#ffffff",
        "border": "#2d2d2d",
        "accent": "#007acc"
    },
    "light": {
        "main_bg": "#f3f3f3",
        "output_bg": "#ffffff",
        "text_color": "#333333",
        "tab_bg": "#e1e1e1",
        "tab_selected_bg": "#ffffff",
        "tab_text": "#666666",
        "tab_selected_text": "#000000",
        "border": "#cccccc",
        "accent": "#005a9e"
    }
}

# ---------------- 获取系统名称辅助函数 ----------------
def get_os_name():
    """读取 /etc/os-release 获取系统名称，失败则回退到内核信息"""
    try:
        with open("/etc/os-release", "r") as f:
            for line in f:
                if line.startswith("NAME="):
                    # 移除 NAME= 和两边的引号
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    except Exception:
        pass
    
    # 兜底逻辑：如果不是 Linux 或者文件不存在，输出系统+内核版本
    return f"{platform.system()} {platform.release()}"

# ---------------- 设置对话框 ----------------
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(400, 250)
        self.settings = QSettings("AzenDev", "DeepTerminal")
        
        layout = QFormLayout(self)

        # 1. 提示符
        self.prompt_input = QLineEdit()
        self.prompt_input.setText(self.settings.value("prompt", "DT ({path})::: "))
        self.prompt_input.setToolTip("Use {path} for current directory.")
        layout.addRow("Prompt Format:", self.prompt_input)

        # 2. 主题切换
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light"])
        current_theme = self.settings.value("theme", "dark")
        self.theme_combo.setCurrentText("Dark" if current_theme == "dark" else "Light")
        layout.addRow("Theme:", self.theme_combo)

        # 3. 启动执行指令
        self.startup_cmd = QLineEdit()
        self.startup_cmd.setText(self.settings.value("startup_cmd", ""))
        self.startup_cmd.setPlaceholderText("e.g., echo 'Hello'")
        layout.addRow("Startup Command:", self.startup_cmd)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save_settings)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def save_settings(self):
        self.settings.setValue("prompt", self.prompt_input.text())
        self.settings.setValue("theme", self.theme_combo.currentText().lower())
        self.settings.setValue("startup_cmd", self.startup_cmd.text())
        self.accept()

# ---------------- 终端实例 ----------------
class TerminalSession(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.history = []
        self.history_index = 0
        self.settings = QSettings("AzenDev", "DeepTerminal")
        
        self._init_ui()
        self._start_process()
        self.apply_theme()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Monospace", 11))
        layout.addWidget(self.output, 1)

        self.input = QLineEdit()
        self.input.setFont(QFont("Monospace", 11))
        self.input.setPlaceholderText("Type a command and press Enter...")
        self.input.returnPressed.connect(self._run_command)
        self.input.installEventFilter(self)
        layout.addWidget(self.input)

    def apply_theme(self):
        theme = self.settings.value("theme", "dark")
        colors = THEMES.get(theme, THEMES["dark"])
        
        self.output.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {colors['output_bg']};
                color: {colors['text_color']};
                border: none;
                padding: 12px;
                selection-background-color: {colors['accent']};
            }}
        """)
        self.input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {colors['main_bg']};
                color: {colors['text_color']};
                border: none;
                border-top: 1px solid {colors['border']};
                padding: 10px;
            }}
            QLineEdit:focus {{ border-top: 1px solid {colors['border']}; outline: none; }}
        """)

    def _start_process(self):
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        
        prompt_format = self.settings.value("prompt", "DT ({path})::: ")
        ps_prompt = prompt_format.replace("{path}", "$(Get-Location)")
        
        args = [
            "-NoLogo", "-NoExit", "-Command",
            f"function prompt {{ \"{ps_prompt}\" }}; $env:PAGER = 'cat'; $OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8"
        ]
        
        exe = "pwsh.exe" if sys.platform == "win32" else "pwsh"
        self.process.start(exe, args)
        self.output.appendPlainText("[DeepTerminal] Starting pwsh...\n")

        startup_cmd = self.settings.value("startup_cmd", "")
        if startup_cmd:
            self.process.write((startup_cmd + "\r\n").encode("utf-8"))

    def _run_command(self):
        cmd = self.input.text().strip()
        if not cmd:
            return
        
        self.input.clear()
        self.history.append(cmd)
        self.history_index = len(self.history)
        
        # 拦截内置指令 terinfo
        if cmd.lower() == "terinfo":
            self._show_terinfo()
            return

        if self.process.state() != QProcess.ProcessState.Running:
            self.output.appendPlainText("[pwsh is not running]")
            return

        self.process.write((cmd + "\r\n").encode("utf-8"))

    def _show_terinfo(self):
        """内置命令 terinfo 显示系统信息"""
        try:
            ps_ver = subprocess.check_output(["pwsh", "-c", "$PSVersionTable.PSVersion.ToString()"], text=True).strip()
        except Exception:
            ps_ver = "Unknown"

        os_name = get_os_name()

        info = (
            f"\n--- DeepTerminal Info ---\n"
            f"DeepTerminal Version : {APP_VERSION}\n"
            f"PowerShell Version   : {ps_ver}\n"
            f"Operating System     : {os_name}\n"
            f"Python Version       : {platform.python_version()}\n"
            f"-------------------------\n"
        )
        self.output.appendPlainText(info)

    def _read_output(self):
        if not self.process: return
        data = self.process.readAllStandardOutput().data()
        text = data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        
        text = ANSI_CONTROL_RE.sub("", text)
        
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        current_color = QColor("#d4d4d4")
        pos = 0
        
        for match in ANSI_COLOR_RE.finditer(text):
            if match.start() > pos:
                fmt = QTextCharFormat()
                fmt.setForeground(current_color)
                cursor.insertText(text[pos:match.start()], fmt)
                
            codes = match.group(1).split(';')
            for code in codes:
                if code == '0' or code == '':
                    current_color = QColor("#d4d4d4")
                elif code.isdigit() and int(code) in ANSI_COLORS:
                    current_color = QColor(ANSI_COLORS[int(code)])
            pos = match.end()

        if pos < len(text):
            fmt = QTextCharFormat()
            fmt.setForeground(current_color)
            cursor.insertText(text[pos:], fmt)
            
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == event.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Up:
                if self.history:
                    self.history_index = max(0, self.history_index - 1)
                    self.input.setText(self.history[self.history_index])
                return True
            if key == Qt.Key.Key_Down:
                if self.history:
                    self.history_index = min(len(self.history), self.history_index + 1)
                    if self.history_index == len(self.history):
                        self.input.clear()
                    else:
                        self.input.setText(self.history[self.history_index])
                return True
        return super().eventFilter(obj, event)

    def clear_output(self):
        self.output.clear()

    def shutdown(self):
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            try:
                self.process.write(b"exit\r\n")
                if not self.process.waitForFinished(500):
                    self.process.kill()
            except Exception:
                pass

# ---------------- 自定义标签栏 ----------------
class CustomTabBar(QTabBar):
    def mousePressEvent(self, event):
        index = self.tabAt(event.position().toPoint())
        if index != -1:
            tab_rect = self.tabRect(index)
            if event.position().x() > tab_rect.right() - 30:
                parent = self.parent()
                while parent and not isinstance(parent, QTabWidget):
                    parent = parent.parent()
                if parent:
                    parent.tabCloseRequested.emit(index)
                return
        super().mousePressEvent(event)

# ---------------- 主窗口 ----------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1000, 680)
        self.settings = QSettings("AzenDev", "DeepTerminal")
        
        self._build_ui()
        self._install_shortcuts()
        self.apply_theme()
        self.new_tab()

    def _build_ui(self):
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.custom_bar = CustomTabBar()
        self.custom_bar.setExpanding(True)
        self.custom_bar.setUsesScrollButtons(False)
        self.tabs.setTabBar(self.custom_bar)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        
        self.custom_bar.installEventFilter(self)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(30, 30)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self.open_settings)
        self.tabs.setCornerWidget(self.settings_btn, Qt.Corner.TopLeftCorner)

        self.new_btn = QPushButton("+ New Tab")
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.clicked.connect(self.new_tab)
        self.tabs.setCornerWidget(self.new_btn, Qt.Corner.TopRightCorner)

        self.counter = QLabel("1 session")
        self.statusBar().addWidget(self.counter)

        self.setCentralWidget(self.tabs)

    def apply_theme(self):
        theme = self.settings.value("theme", "dark")
        colors = THEMES.get(theme, THEMES["dark"])
        
        self.setStyleSheet(f"QMainWindow {{ background-color: {colors['main_bg']}; }}")
        
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; background: {colors['output_bg']}; }}
            QTabBar::tab {{
                background: {colors['tab_bg']};
                color: {colors['tab_text']};
                padding: 8px 30px;
                border-right: 1px solid {colors['border']};
                border-radius: 0px;
            }}
            QTabBar::tab:selected {{ background: {colors['tab_selected_bg']}; color: {colors['tab_selected_text']}; }}
            QTabBar::tab:hover:!selected {{ background: {colors['border']}; color: {colors['tab_selected_text']}; }}
        """)
        
        self.settings_btn.setStyleSheet(f"""
            QPushButton {{ background: {colors['tab_bg']}; color: {colors['tab_text']}; border: none; font-size: 16px; }}
            QPushButton:hover {{ background: {colors['border']}; color: {colors['tab_selected_text']}; }}
        """)
        
        self.new_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {colors['tab_text']}; border: none; padding: 8px 16px; font-weight: bold; }}
            QPushButton:hover {{ background: {colors['border']}; color: {colors['tab_selected_text']}; }}
        """)
        
        self.statusBar().setStyleSheet(f"""
            QStatusBar {{ background-color: {colors['main_bg']}; color: {colors['tab_text']}; border-top: 1px solid {colors['border']}; }}
        """)

        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, TerminalSession):
                widget.apply_theme()

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_theme()

    def eventFilter(self, obj, event):
        if obj is self.custom_bar and event.type() == event.Type.MouseButtonDblClick:
            index = self.custom_bar.tabAt(event.position().toPoint())
            if index != -1:
                tab_rect = self.custom_bar.tabRect(index)
                if event.position().x() <= tab_rect.right() - 30:
                    current_name = self.tabs.tabText(index)
                    new_name, ok = QInputDialog.getText(self, "Rename Tab", "Enter new name:", text=current_name)
                    if ok and new_name.strip():
                        self.tabs.setTabText(index, new_name.strip())
                    return True
        return super().eventFilter(obj, event)

    def _install_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Shift+T"), self, activated=self.new_tab)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self._close_current)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._clear_current)

    def new_tab(self):
        tab = TerminalSession()
        idx = self.tabs.addTab(tab, f"pwsh {self.tabs.count() + 1}")
        self.tabs.setCurrentIndex(idx)
        tab.input.setFocus()
        self._update_counter()

    def close_tab(self, index):
        w = self.tabs.widget(index)
        if isinstance(w, TerminalSession):
            w.shutdown()
        self.tabs.removeTab(index)
        self._update_counter()

    def _close_current(self):
        if self.tabs.count() > 0:
            self.close_tab(self.tabs.currentIndex())

    def _clear_current(self):
        w = self.tabs.currentWidget()
        if isinstance(w, TerminalSession):
            w.clear_output()

    def _update_counter(self):
        n = self.tabs.count()
        self.counter.setText(f"{n} session" + ("" if n == 1 else "s"))

    def closeEvent(self, event):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, TerminalSession):
                w.shutdown()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("DeepTerminal")
    
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deepterm.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
