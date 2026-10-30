import sys
import re
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPlainTextEdit, QLineEdit, QTabWidget, QPushButton, QLabel
)
from PyQt6.QtCore import QProcess, Qt
from PyQt6.QtGui import QFont, QShortcut, QKeySequence

APP_TITLE = "DeepTerminal beta"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

class TerminalSession(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.history = []
        self.history_index = 0
        self._init_ui()
        self._start_process()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Monospace", 11))
        self.output.setStyleSheet("""
            QPlainTextEdit {
                background-color: #141414;
                color: #d4d4d4;
                border: none;
                padding: 12px;
                selection-background-color: #264f78;
            }
        """)
        layout.addWidget(self.output, 1)

        self.input = QLineEdit()
        self.input.setFont(QFont("Monospace", 11))
        self.input.setPlaceholderText("Type a command and press Enter...")
        self.input.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                border-top: 1px solid #333333;
                padding: 10px;
            }
            QLineEdit:focus { 
                border-top: 1px solid #007acc; 
            }
        """)
        self.input.returnPressed.connect(self._run_command)
        self.input.installEventFilter(self)
        layout.addWidget(self.input)

    def _start_process(self):
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)
        
        # 核心修改：修改 prompt 函数，使其输出 "DT (路径)::: "
        args = [
            "-NoLogo",
            "-NoExit",
            "-Command",
            "$PSStyle.OutputRendering = 'PlainText'; "
            "function prompt { \"DT ($(Get-Location))::: \" }; "
            "$env:PAGER = 'cat'; "
            "$OutputEncoding = [System.Text.Encoding]::UTF8; "
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8"
        ]
        
        exe = "pwsh"
        if sys.platform == "win32":
            exe = "pwsh.exe"

        self.process.start(exe, args)
        self.output.appendPlainText("[DeepTerminal] Starting pwsh...\n")

    def _run_command(self):
        if self.process.state() != QProcess.ProcessState.Running:
            self.output.appendPlainText("[pwsh is not running]")
            return
        cmd = self.input.text().strip()
        if not cmd:
            return
        
        self.input.clear()
        self.history.append(cmd)
        self.history_index = len(self.history)
        
        self.process.write((cmd + "\r\n").encode("utf-8"))

    def _read_output(self):
        if not self.process:
            return
        data = self.process.readAllStandardOutput().data()
        text = data.decode("utf-8", errors="replace")
        text = ANSI_RE.sub("", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        
        cursor = self.output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.output.setTextCursor(cursor)
        self.output.insertPlainText(text)
        self.output.ensureCursorVisible()

    def _on_finished(self, code, status):
        self.output.appendPlainText(f"\n[pwsh exited with code {code}]")

    def _on_error(self, error):
        self.output.appendPlainText(f"\n[Process error: {error}]")

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
                    self.process.waitForFinished(100)
            except Exception:
                pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1000, 680)
        self._build_ui()
        self._install_shortcuts()
        self.new_tab()

    def _build_ui(self):
        self.setStyleSheet("QMainWindow { background-color: #1e1e1e; }")

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._update_counter)
        
        self.tabs.setStyleSheet("""
            QTabWidget::pane { 
                border: none; 
                background: #141414;
            }
            QTabBar::tab {
                background: #1e1e1e;
                color: #858585;
                padding: 8px 24px;
                border-right: 1px solid #2d2d2d;
                border-bottom: 2px solid transparent;
                border-radius: 0px;
            }
            QTabBar::tab:selected { 
                background: #141414;
                color: #ffffff; 
                border-bottom: 2px solid #007acc;
            }
            QTabBar::tab:hover:!selected { 
                background: #2d2d2d; 
                color: #cccccc;
            }
        """)

        self.new_btn = QPushButton("+ New Tab")
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #cccccc;
                border: none;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { 
                background-color: #2d2d2d; 
                color: #ffffff;
            }
        """)
        self.new_btn.clicked.connect(self.new_tab)
        self.tabs.setCornerWidget(self.new_btn, Qt.Corner.TopRightCorner)

        self.counter = QLabel("1 session")
        self.statusBar().addWidget(self.counter)
        self.statusBar().setStyleSheet("""
            QStatusBar {
                background-color: #1e1e1e;
                color: #858585;
                border-top: 1px solid #2d2d2d;
            }
        """)

        self.setCentralWidget(self.tabs)

    def _install_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Shift+T"), self, activated=self.new_tab)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self._close_current)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._clear_current)
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=self._next_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=self._prev_tab)

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

    def _next_tab(self):
        if self.tabs.count() > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % self.tabs.count())

    def _prev_tab(self):
        if self.tabs.count() > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % self.tabs.count())

    def _update_counter(self, *_):
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
    window = MainWindow()
    window.show()
    sys.exit(app.exec())