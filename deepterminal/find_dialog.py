"""Non-modal find bar for the active terminal."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from .view import TerminalView


class FindDialog(QDialog):
    """Search the active terminal's scrollback and screen."""

    def __init__(self, view: TerminalView, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.view = view
        self.setWindowTitle("Find")
        self.setMinimumWidth(340)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Find in terminal…")
        self.edit.textChanged.connect(self._on_text)
        self.edit.returnPressed.connect(lambda: self._step(1))
        row.addWidget(self.edit, 1)
        previous = QPushButton("↑")
        previous.setToolTip("Previous match (Shift+Enter)")
        previous.setFixedWidth(30)
        previous.clicked.connect(lambda: self._step(-1))
        row.addWidget(previous)
        following = QPushButton("↓")
        following.setToolTip("Next match (Enter)")
        following.setFixedWidth(30)
        following.clicked.connect(lambda: self._step(1))
        row.addWidget(following)
        close = QPushButton("✕")
        close.setToolTip("Close (Esc)")
        close.setFixedWidth(30)
        close.clicked.connect(self.close)
        row.addWidget(close)
        outer.addLayout(row)
        self.status = QLabel("")
        self.status.setStyleSheet("color: palette(mid);")
        outer.addWidget(self.status)

        QShortcut(QKeySequence("Shift+Return"), self, activated=lambda: self._step(-1))
        QShortcut(QKeySequence("Escape"), self, activated=self.close)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self.edit.setFocus()
        self.edit.selectAll()
        if self.edit.text() == "":
            selected = self.view.selection().strip()
            if selected and "\n" not in selected:
                self.edit.setText(selected)

    def _on_text(self, text: str) -> None:
        count = self.view.set_search(text)
        if text == "":
            self.status.setText("")
        elif count == 0:
            self.status.setText("No matches")
        else:
            self.status.setText(f"{count} match{'es' if count != 1 else ''}")

    def _step(self, delta: int) -> None:
        self.view.search_step(delta)
        total = len(self.view.search_matches())
        if total > 0:
            self.status.setText(f"{self.view.search_position() + 1} / {total}")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.view.clear_search()
        super().closeEvent(event)
