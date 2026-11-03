"""Main window: tabbed terminals, settings, shortcuts."""

from __future__ import annotations

import platform
from importlib.metadata import version as package_version

from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabBar,
    QTabWidget,
    QToolButton,
)

from .config import APP_NAME, APP_VERSION, Config
from .find_dialog import FindDialog
from .settings_dialog import SettingsDialog
from .shells import ShellError, resolve_profile
from .view import TerminalView


class MainWindow(QMainWindow):
    """DeepTerminal main window."""

    def __init__(self, config: Config | None = None, shell_key: str | None = None, working_dir: str | None = None) -> None:
        super().__init__()
        self.config = config if config is not None else Config()
        if working_dir:
            self.config.set("working_dir", working_dir)
        self.default_shell = shell_key or self.config.get_str("shell")
        self._find_dialog: FindDialog | None = None
        self._renamed_tabs: set[TerminalView] = set()

        self.setWindowTitle(APP_NAME)
        self.resize(1080, 700)
        geometry = self.config.geometry()
        if geometry:
            self.restoreGeometry(geometry)

        self._build_ui()
        self._install_shortcuts()
        self._apply_chrome()
        if self.new_tab() is None and self.default_shell != "bash":
            # Do not leave an empty window when the saved shell disappears.
            self.default_shell = "bash"
            self.new_tab("bash")

    # -- ui --------------------------------------------------------------
    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabBar().installEventFilter(self)
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_menu)
        self.setCentralWidget(self.tabs)

        settings_button = QPushButton("⚙")
        settings_button.setObjectName("settingsButton")
        settings_button.setFixedSize(30, 30)
        settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_button.setToolTip("Settings")
        settings_button.clicked.connect(self.open_settings)
        self.tabs.setCornerWidget(settings_button, Qt.Corner.TopLeftCorner)

        self.new_button = QToolButton()
        self.new_button.setText("＋  New Tab")
        self.new_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.new_button.setToolTip("New tab (Ctrl+Shift+T)")
        self.new_button.setMenu(self._build_new_menu())
        self.tabs.setCornerWidget(self.new_button, Qt.Corner.TopRightCorner)

        self.status_label = QLabel("")
        self.statusBar().addWidget(self.status_label)

    def _build_new_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("PowerShell 7", lambda: self.new_tab("pwsh"))
        menu.addAction("Bash", lambda: self.new_tab("bash"))
        menu.addAction("Custom command…", lambda: self.new_tab("custom"))
        menu.addSeparator()
        menu.addAction("Settings…", self.open_settings)
        menu.addAction("About DeepTerminal", self.show_about)
        return menu

    def _apply_chrome(self) -> None:
        theme = self.config.theme()
        self.setStyleSheet(
            f"""
            QMainWindow {{ background: {theme['window_bg']}; }}
            QTabWidget::pane {{ border: none; background: {theme['bg']}; }}
            QTabBar::tab {{
                background: {theme['tab_bg']};
                color: {theme['tab_fg']};
                padding: 8px 26px;
                border-right: 1px solid {theme['border']};
                border-radius: 0;
            }}
            QTabBar::tab:selected {{ background: {theme['tab_active_bg']}; color: {theme['tab_active_fg']}; }}
            QTabBar::tab:hover:!selected {{ background: {theme['border']}; color: {theme['tab_active_fg']}; }}
            QToolButton#tabClose {{
                background: transparent;
                color: {theme['tab_fg']};
                border: none;
                padding: 0;
                font-weight: 600;
            }}
            QToolButton#tabClose:hover {{
                background: {theme['border']};
                color: {theme['tab_active_fg']};
                border-radius: 4px;
            }}
            QPushButton#settingsButton, QToolButton {{
                background: transparent;
                color: {theme['tab_fg']};
                border: none;
                padding: 6px 12px;
                font-weight: 600;
            }}
            QToolButton:hover, QPushButton#settingsButton:hover {{
                background: {theme['border']};
                color: {theme['tab_active_fg']};
            }}
            QStatusBar {{ background: {theme['window_bg']}; color: {theme['tab_fg']}; border-top: 1px solid {theme['border']}; }}
            QMenu {{ background: {theme['window_bg']}; color: {theme['fg']}; border: 1px solid {theme['border']}; }}
            QMenu::item:selected {{ background: {theme['accent']}; color: #ffffff; }}
            """
        )

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Shift+T"), self, activated=self.new_tab)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close_current_tab)
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self.cycle_tab(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=lambda: self.cycle_tab(-1))
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.open_settings)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, activated=self.open_find)
        QShortcut(QKeySequence("F11"), self, activated=self.toggle_fullscreen)

    # -- tabs ------------------------------------------------------------
    def new_tab(self, shell_key: str | None = None) -> TerminalView | None:
        try:
            profile = resolve_profile(self.config, shell_key or self.default_shell)
        except ShellError as error:
            QMessageBox.warning(self, "Shell unavailable", str(error))
            return None
        view = TerminalView(self.config, profile)
        view.title_changed.connect(lambda title, widget=view: self._on_title_changed(widget, title))
        view.restart_requested.connect(lambda widget=view: widget.restart())
        view.find_requested.connect(self.open_find)
        view.size_changed.connect(self._update_status)
        index = self.tabs.addTab(view, profile.label)
        self.tabs.setTabToolTip(index, f"{profile.label} — {' '.join(profile.argv)}")
        self._install_close_button(view)
        self.tabs.setCurrentIndex(index)
        view.setFocus()
        self._update_status()
        return view

    def _install_close_button(self, view: TerminalView) -> None:
        button = QToolButton()
        button.setObjectName("tabClose")
        button.setText("✕")
        button.setFixedSize(18, 18)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.ArrowCursor)
        button.setToolTip("Close tab")
        button.clicked.connect(lambda _checked=False, widget=view: self.close_tab(self.tabs.indexOf(widget)))
        index = self.tabs.indexOf(view)
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, button)

    def close_tab(self, index: int) -> None:
        view = self.tabs.widget(index)
        if isinstance(view, TerminalView):
            view.shutdown()
            self._renamed_tabs.discard(view)
        self.tabs.removeTab(index)
        if isinstance(view, TerminalView):
            view.deleteLater()
        if self.tabs.count() == 0:
            self.close()
        self._update_status()

    def close_current_tab(self) -> None:
        if self.tabs.count() > 0:
            self.close_tab(self.tabs.currentIndex())

    def cycle_tab(self, delta: int) -> None:
        count = self.tabs.count()
        if count > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + delta) % count)

    def _rename_tab(self, index: int) -> None:
        current = self.tabs.tabText(index)
        name, accepted = QInputDialog.getText(self, "Rename Tab", "Tab name:", text=current)
        if accepted and name.strip() != "":
            self.tabs.setTabText(index, name.strip())
            view = self.tabs.widget(index)
            if isinstance(view, TerminalView):
                self._renamed_tabs.add(view)

    def _tab_menu(self, point) -> None:
        index = self.tabs.tabBar().tabAt(point)
        if index < 0:
            return
        menu = QMenu(self)
        menu.addAction("Rename…", lambda: self._rename_tab(index))
        view = self.tabs.widget(index)
        if isinstance(view, TerminalView):
            if view in self._renamed_tabs:
                menu.addAction("Use shell title", lambda: self._restore_shell_title(view))
            menu.addAction("Restart shell", view.restart)
            menu.addAction("Duplicate tab", lambda: self.new_tab(view.profile.key))
        menu.addSeparator()
        menu.addAction("Close", lambda: self.close_tab(index))
        menu.exec(self.tabs.tabBar().mapToGlobal(point))

    def _restore_shell_title(self, view: TerminalView) -> None:
        self._renamed_tabs.discard(view)
        title = getattr(view.emulator, "title", "") or view.profile.label
        index = self.tabs.indexOf(view)
        if index >= 0:
            self.tabs.setTabText(index, title)
            if self.tabs.currentIndex() == index:
                self._update_window_title()

    def _on_title_changed(self, view: TerminalView, title: str) -> None:
        index = self.tabs.indexOf(view)
        if index < 0 or view in self._renamed_tabs:
            return
        text = title.strip() or view.profile.label
        self.tabs.setTabText(index, text)
        if self.tabs.currentIndex() == index:
            self._update_window_title()

    def _on_tab_changed(self, index: int) -> None:
        if self._find_dialog is not None:
            self._find_dialog.close()
            self._find_dialog = None
        view = self.tabs.widget(index)
        if isinstance(view, TerminalView):
            view.setFocus()
        self._update_window_title()
        self._update_status()

    def _update_window_title(self) -> None:
        view = self.tabs.currentWidget()
        if isinstance(view, TerminalView):
            title = self.tabs.tabText(self.tabs.currentIndex()) or view.profile.label
            self.setWindowTitle(f"{title} — {APP_NAME}")
        else:
            self.setWindowTitle(APP_NAME)

    def _update_status(self) -> None:
        count = self.tabs.count()
        view = self.tabs.currentWidget()
        if isinstance(view, TerminalView):
            text = f"{count} session{'s' if count != 1 else ''} · {view.profile.label} · {view.size_text()}"
        else:
            text = f"{count} sessions"
        self.status_label.setText(text)

    # -- events ----------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt naming
        if obj is self.tabs.tabBar() and event.type() == QEvent.Type.MouseButtonDblClick:
            index = self.tabs.tabBar().tabAt(event.position().toPoint())
            if index != -1:
                self._rename_tab(index)
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._find_dialog is not None:
            self._find_dialog.close()
            self._find_dialog = None
        self.config.save_geometry(bytes(self.saveGeometry()))
        for index in range(self.tabs.count()):
            view = self.tabs.widget(index)
            if isinstance(view, TerminalView):
                view.shutdown()
        self.config.sync()
        super().closeEvent(event)

    # -- actions ---------------------------------------------------------
    def open_find(self) -> None:
        view = self.tabs.currentWidget()
        if not isinstance(view, TerminalView):
            return
        if self._find_dialog is not None:
            if self._find_dialog.view is view and self._find_dialog.isVisible():
                self._find_dialog.raise_()
                self._find_dialog.edit.setFocus()
                return
            self._find_dialog.close()
            self._find_dialog = None
        dialog = FindDialog(view, self)
        dialog.adjustSize()
        position = self.pos() + QPoint(self.width() - dialog.width() - 48, 72)
        dialog.move(position)
        dialog.show()
        self._find_dialog = dialog

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.default_shell = self.config.get_str("shell")
            self._apply_chrome()
            for index in range(self.tabs.count()):
                view = self.tabs.widget(index)
                if isinstance(view, TerminalView):
                    view.apply_settings()
            self._update_status()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def show_about(self) -> None:
        try:
            pyte_version = package_version("pyte")
        except Exception:
            pyte_version = "unknown"
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

        text = (
            f"<b>{APP_NAME} {APP_VERSION}</b><br>"
            "A native Qt terminal for PowerShell, Bash and any shell.<br><br>"
            f"Python {platform.python_version()}<br>"
            f"Qt {QT_VERSION_STR} · PyQt {PYQT_VERSION_STR}<br>"
            f"pyte {pyte_version}<br>"
            f"Kernel {platform.release()}<br><br>"
            f"pty: real pseudo-terminal · {self.tabs.count()} session(s)<br>"
            "Shortcuts: Ctrl+Shift+T new tab, Ctrl+W close, Ctrl+Tab switch, "
            "Ctrl+Shift+C/V copy/paste, Ctrl+= / Ctrl+- / Ctrl+0 zoom, F11 fullscreen."
        )
        QMessageBox.about(self, f"About {APP_NAME}", text)
