"""Settings dialog for DeepTerminal: sidebar navigation + stacked pages."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .config import DEFAULTS, Config, theme_names
from .promptstyle import COLOR_ORDER, COLORS, PRESETS, STYLE_ORDER, preview_html
from .shells import shell_choices

#: (page id, sidebar label) in display order.
PAGE_ORDER = (("general", "General"), ("appearance", "Appearance"), ("prompt", "Prompt"))


def monospace_families() -> list[str]:
    """Return installed fixed-pitch families for the font chooser."""
    families = []
    for family in QFontDatabase.families():
        if QFontInfo(QFont(family)).fixedPitch():
            families.append(family)
    return sorted(families, key=str.lower)


class SettingsDialog(QDialog):
    """Edit the settings stored in QSettings."""

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings — DeepTerminal")
        self.setMinimumSize(740, 500)
        self._user_host_before_powerline = config.get_bool("prompt_user_host")
        self._build()
        self._apply_style()
        self._sync_prompt_state()

    # -- construction ----------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sideBar")
        self.sidebar.setFixedWidth(170)
        for key, label in PAGE_ORDER:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.sidebar.addItem(item)
        self.sidebar.setCurrentRow(0)
        self.sidebar.currentRowChanged.connect(self._on_page)
        body.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_general_page())
        self.pages.addWidget(self._build_appearance_page())
        self.pages.addWidget(self._build_prompt_page())
        page_wrap = QVBoxLayout()
        page_wrap.setContentsMargins(24, 20, 24, 12)
        page_wrap.addWidget(self.pages)
        body.addLayout(page_wrap, 1)
        outer.addLayout(body)

        footer = QHBoxLayout()
        footer.setContentsMargins(24, 4, 24, 14)
        note = QLabel(
            "Shell, prompt style and startup command apply to <b>new tabs</b>. "
            "Theme, font and cursor blink apply immediately."
        )
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.RichText)
        note.setStyleSheet("color: palette(mid);")
        footer.addWidget(note, 1)
        buttons = QDialogButtonBox()
        restore = buttons.addButton("Restore Defaults", QDialogButtonBox.ButtonRole.ResetRole)
        restore.clicked.connect(self._restore_defaults)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.addButton(QDialogButtonBox.StandardButton.Ok)
        ok.setDefault(True)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        outer.addLayout(footer)

    def _page(self, layout_factory) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout_factory(form)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _build_general_page(self) -> QWidget:
        def build(form: QFormLayout) -> None:
            self.shell_combo = QComboBox()
            for key, label, availability in shell_choices():
                self.shell_combo.addItem(label, key)
                self.shell_combo.setItemData(self.shell_combo.count() - 1, availability, Qt.ItemDataRole.ToolTipRole)
            current_shell = self.config.get_str("shell")
            self.shell_combo.setCurrentIndex(max(0, self.shell_combo.findData(current_shell)))
            self.shell_combo.currentIndexChanged.connect(self._sync_custom_enabled)
            form.addRow("Default shell:", self.shell_combo)

            self.custom_edit = QLineEdit(self.config.get_str("custom_shell"))
            self.custom_edit.setPlaceholderText("e.g. fish -i  ·  /bin/zsh -l  ·  nu")
            form.addRow("Custom command:", self.custom_edit)

            self.startup_edit = QLineEdit(self.config.get_str("startup_cmd"))
            self.startup_edit.setPlaceholderText("Command typed into every new tab (optional)")
            form.addRow("Startup command:", self.startup_edit)

            working_row = QHBoxLayout()
            self.working_edit = QLineEdit(self.config.get_str("working_dir"))
            self.working_edit.setPlaceholderText("Default: home directory")
            working_row.addWidget(self.working_edit, 1)
            browse = QPushButton("Browse…")
            browse.clicked.connect(self._browse_directory)
            working_row.addWidget(browse)
            form.addRow("Start directory:", working_row)

        page = self._page(build)
        self._sync_custom_enabled()
        return page

    def _build_appearance_page(self) -> QWidget:
        def build(form: QFormLayout) -> None:
            self.theme_combo = QComboBox()
            for name in theme_names():
                self.theme_combo.addItem(name.capitalize(), name)
            self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(self.config.get_str("theme"))))
            form.addRow("Theme:", self.theme_combo)

            font_row = QHBoxLayout()
            self.font_combo = QComboBox()
            self.font_combo.addItem("System monospace", "")
            for family in monospace_families():
                self.font_combo.addItem(family, family)
            self.font_combo.setCurrentIndex(max(0, self.font_combo.findData(self.config.get_str("font_family"))))
            font_row.addWidget(self.font_combo, 1)
            self.font_size = QSpinBox()
            self.font_size.setRange(6, 32)
            self.font_size.setValue(self.config.get_int("font_size"))
            self.font_size.setSuffix(" pt")
            font_row.addWidget(self.font_size)
            form.addRow("Terminal font:", font_row)

            self.scrollback = QSpinBox()
            self.scrollback.setRange(500, 100_000)
            self.scrollback.setSingleStep(500)
            self.scrollback.setValue(self.config.get_int("scrollback"))
            self.scrollback.setSuffix(" lines")
            form.addRow("Scrollback:", self.scrollback)

            self.blink = QCheckBox("Blink the cursor")
            self.blink.setChecked(self.config.get_bool("cursor_blink"))
            form.addRow("", self.blink)

        return self._page(build)

    def _build_prompt_page(self) -> QWidget:
        def build(form: QFormLayout) -> None:
            self.style_combo = QComboBox()
            for key in STYLE_ORDER:
                self.style_combo.addItem(str(PRESETS[key]["label"]), key)
            current = self.config.get_str("prompt_style").strip().lower() or DEFAULTS["prompt_style"]
            self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(current)))
            self.style_combo.currentIndexChanged.connect(self._sync_prompt_state)
            form.addRow("Style:", self.style_combo)

            self.symbol_edit = QLineEdit(self.config.get_str("prompt_symbol"))
            self.symbol_edit.setPlaceholderText("Preset symbol (any emoji or character)")
            form.addRow("Symbol:", self.symbol_edit)

            self.symbol_color = self._color_combo()
            self.symbol_color.setCurrentIndex(max(0, self.symbol_color.findData(self.config.get_str("prompt_symbol_color"))))
            form.addRow("Symbol color:", self.symbol_color)

            self.path_color = self._color_combo()
            self.path_color.setCurrentIndex(max(0, self.path_color.findData(self.config.get_str("prompt_path_color"))))
            form.addRow("Path color:", self.path_color)

            self.user_host = QCheckBox("Show username@host in the prompt")
            self.user_host.setChecked(self.config.get_bool("prompt_user_host"))
            self.user_host.toggled.connect(self._on_user_host_toggled)
            form.addRow("", self.user_host)

            # ---- Powerline customization (visible only for the Powerline style) ----
            self.pl_mode = QComboBox()
            self.pl_mode.addItem("Full (user@host + path)", "full")
            self.pl_mode.addItem("Path only", "path_only")
            self.pl_mode.addItem("User only", "user_only")
            mode = self.config.get_str("powerline_mode")
            self.pl_mode.setCurrentIndex(max(0, self.pl_mode.findData(mode)))
            self.pl_mode.currentIndexChanged.connect(lambda _i: self._refresh_preview())
            form.addRow("Powerline content:", self.pl_mode)

            self.pl_arrow = QCheckBox("Sharp ▸ tips between segments")
            self.pl_arrow.setChecked(self.config.get_bool("powerline_arrow"))
            self.pl_arrow.toggled.connect(lambda _c: self._refresh_preview())
            form.addRow("", self.pl_arrow)

            def _pl_color(label: str, config_key: str) -> QComboBox:
                combo = self._color_combo()
                current = self.config.get_str(config_key)
                combo.setCurrentIndex(max(0, combo.findData(current)))
                combo.currentIndexChanged.connect(lambda _i: self._refresh_preview())
                form.addRow(label, combo)
                return combo

            self.pl_user_fg = _pl_color("User text color:", "powerline_user_fg")
            self.pl_user_bg = _pl_color("User background:", "powerline_user_bg")
            self.pl_path_fg = _pl_color("Path text color:", "powerline_path_fg")
            self.pl_path_bg = _pl_color("Path background:", "powerline_path_bg")

            self.format_edit = QLineEdit(self.config.get_str("prompt"))
            self.format_edit.setPlaceholderText("DT ({path})::: ")
            self.format_edit.setToolTip("{path} is replaced with the current directory.")
            self.format_edit.textChanged.connect(lambda _text: self._refresh_preview())
            form.addRow("Format:", self.format_edit)

        page = self._page(build)
        layout = page.layout()
        caption = QLabel("Preview")
        caption.setObjectName("previewCaption")
        layout.insertWidget(0, caption)
        self.preview = QLabel()
        self.preview.setObjectName("promptPreview")
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        self.preview.setMinimumHeight(52)
        layout.insertWidget(1, self.preview)
        return page

    def _color_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Preset default", "")
        for name in COLOR_ORDER:
            combo.addItem(QIcon(self._swatch(COLORS[name])), name.capitalize(), name)
        return combo

    @staticmethod
    def _swatch(hexcode: str) -> QPixmap:
        pixmap = QPixmap(14, 14)
        pixmap.fill(QColor(hexcode))
        return pixmap

    # -- styling ---------------------------------------------------------
    def _apply_style(self) -> None:
        theme = self.config.theme()
        self.setStyleSheet(
            f"""
            QDialog {{ background: {theme['window_bg']}; color: {theme['fg']}; }}
            QStackedWidget, QWidget {{ background: {theme['window_bg']}; }}
            QListWidget#sideBar {{
                background: {theme['window_bg']};
                border: none;
                border-right: 1px solid {theme['border']};
                outline: none;
                padding-top: 8px;
            }}
            QListWidget#sideBar::item {{
                color: {theme['tab_fg']};
                padding: 10px 16px;
                border-radius: 8px;
                margin: 2px 10px;
            }}
            QListWidget#sideBar::item:selected {{
                background: {theme['border']};
                color: {theme['tab_active_fg']};
                font-weight: 600;
            }}
            QListWidget#sideBar::item:hover:!selected {{ background: {theme['bg']}; }}
            QLabel {{ color: {theme['fg']}; }}
            QLabel#previewCaption {{ color: {theme['tab_fg']}; font-weight: 600; padding-bottom: 2px; }}
            QLabel#promptPreview {{
                background: {theme['bg']};
                color: {theme['fg']};
                border: 1px solid {theme['border']};
                border-radius: 8px;
                padding: 12px 14px;
            }}
            QLineEdit, QSpinBox, QComboBox {{
                background: {theme['bg']};
                color: {theme['fg']};
                border: 1px solid {theme['border']};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {theme['accent']}; }}
            QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QCheckBox:disabled {{
                color: {theme['tab_fg']};
                background: {theme['window_bg']};
            }}
            QComboBox::drop-down {{ border: none; width: 22px; }}
            QComboBox QAbstractItemView {{
                background: {theme['bg']};
                color: {theme['fg']};
                border: 1px solid {theme['border']};
                selection-background-color: {theme['accent']};
                selection-color: #ffffff;
                outline: none;
            }}
            QCheckBox {{ color: {theme['fg']}; spacing: 8px; }}
            QPushButton {{
                background: {theme['border']};
                color: {theme['fg']};
                border: none;
                border-radius: 6px;
                padding: 7px 16px;
            }}
            QPushButton:hover {{ background: {theme['accent']}; color: #ffffff; }}
            QDialogButtonBox QPushButton {{ min-width: 86px; }}
            QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; background: transparent; border: none; }}
            """
        )
        family = self.config.get_str("font_family").strip() or "Monospace"
        preview_font = QFont(family)
        preview_font.setStyleHint(QFont.StyleHint.Monospace)
        preview_font.setPointSize(max(8, self.config.get_int("font_size")))
        self.preview.setFont(preview_font)

    # -- behaviour -------------------------------------------------------
    def _on_page(self, row: int) -> None:
        self.pages.setCurrentIndex(row)

    def _sync_custom_enabled(self) -> None:
        self.custom_edit.setEnabled(self.shell_combo.currentData() == "custom")

    def _sync_prompt_state(self) -> None:
        key = self.style_combo.currentData()
        custom = key == "custom"
        none = key == "none"
        powerline = key == "powerline"
        if powerline:
            # Powerline always shows username@host; remember what the user
            # had chosen so it comes back when another style is selected.
            self.user_host.blockSignals(True)
            self.user_host.setChecked(True)
            self.user_host.blockSignals(False)
        elif not custom and not none:
            self.user_host.blockSignals(True)
            self.user_host.setChecked(self._user_host_before_powerline)
            self.user_host.blockSignals(False)
        self.format_edit.setEnabled(custom)
        self.symbol_edit.setEnabled(not custom and not none)
        self.symbol_color.setEnabled(not custom and not none and not powerline)
        self.path_color.setEnabled(not custom and not none and not powerline)
        self.user_host.setEnabled(not custom and not none and not powerline)
        # Powerline-only controls
        for widget in (self.pl_mode, self.pl_arrow, self.pl_user_fg,
                       self.pl_user_bg, self.pl_path_fg, self.pl_path_bg):
            widget.setEnabled(powerline)
            widget.setVisible(powerline)
        self._refresh_preview()

    def _on_user_host_toggled(self, checked: bool) -> None:
        if self.style_combo.currentData() != "powerline":
            self._user_host_before_powerline = checked
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self.preview.setText(
            preview_html(
                self.style_combo.currentData(),
                symbol=self.symbol_edit.text(),
                symbol_color=self.symbol_color.currentData() or "",
                path_color=self.path_color.currentData() or "",
                user_host=self.user_host.isChecked(),
                custom_format=self.format_edit.text(),
                powerline_mode=self.pl_mode.currentData(),
                powerline_arrow=self.pl_arrow.isChecked(),
                pl_user_fg=self.pl_user_fg.currentData() or "",
                pl_user_bg=self.pl_user_bg.currentData() or "",
                pl_path_fg=self.pl_path_fg.currentData() or "",
                pl_path_bg=self.pl_path_bg.currentData() or "",
            )
        )

    def _browse_directory(self) -> None:
        current = self.working_edit.text().strip() or self.config.working_dir()
        chosen = QFileDialog.getExistingDirectory(self, "Start directory", current)
        if chosen:
            self.working_edit.setText(chosen)

    def _restore_defaults(self) -> None:
        self.shell_combo.setCurrentIndex(max(0, self.shell_combo.findData(DEFAULTS["shell"])))
        self.custom_edit.setText(str(DEFAULTS["custom_shell"]))
        self.startup_edit.setText(str(DEFAULTS["startup_cmd"]))
        self.working_edit.setText(str(DEFAULTS["working_dir"]))
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(DEFAULTS["theme"])))
        self.font_combo.setCurrentIndex(0)
        self.font_size.setValue(int(DEFAULTS["font_size"]))
        self.scrollback.setValue(int(DEFAULTS["scrollback"]))
        self.blink.setChecked(bool(DEFAULTS["cursor_blink"]))
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(DEFAULTS["prompt_style"])))
        self.symbol_edit.setText(str(DEFAULTS["prompt_symbol"]))
        self.symbol_color.setCurrentIndex(0)
        self.path_color.setCurrentIndex(0)
        self._user_host_before_powerline = bool(DEFAULTS["prompt_user_host"])
        self.user_host.setChecked(self._user_host_before_powerline)
        self.pl_mode.setCurrentIndex(max(0, self.pl_mode.findData(DEFAULTS["powerline_mode"])))
        self.pl_arrow.setChecked(bool(DEFAULTS["powerline_arrow"]))
        for combo in (self.pl_user_fg, self.pl_user_bg, self.pl_path_fg, self.pl_path_bg):
            combo.setCurrentIndex(0)
        self.format_edit.setText(str(DEFAULTS["prompt"]))
        self._sync_custom_enabled()
        self._sync_prompt_state()

    def _accept(self) -> None:
        shell = self.shell_combo.currentData()
        if shell == "custom" and self.custom_edit.text().strip() == "":
            QMessageBox.warning(self, "Custom shell", "Enter the command to run, for example: fish -i")
            return
        self.config.apply(self.values())
        self.config.sync()
        self.accept()

    def values(self) -> dict[str, object]:
        return {
            "shell": self.shell_combo.currentData(),
            "custom_shell": self.custom_edit.text().strip(),
            "startup_cmd": self.startup_edit.text(),
            "working_dir": self.working_edit.text().strip(),
            "theme": self.theme_combo.currentData(),
            "font_family": self.font_combo.currentData() or "",
            "font_size": self.font_size.value(),
            "scrollback": self.scrollback.value(),
            "cursor_blink": self.blink.isChecked(),
            "prompt": self.format_edit.text(),
            "prompt_style": self.style_combo.currentData(),
            "prompt_symbol": self.symbol_edit.text().strip(),
            "prompt_symbol_color": self.symbol_color.currentData() or "",
            "prompt_path_color": self.path_color.currentData() or "",
            "prompt_user_host": self.user_host.isChecked(),
            "powerline_mode": self.pl_mode.currentData(),
            "powerline_arrow": self.pl_arrow.isChecked(),
            "powerline_user_fg": self.pl_user_fg.currentData() or "",
            "powerline_user_bg": self.pl_user_bg.currentData() or "",
            "powerline_path_fg": self.pl_path_fg.currentData() or "",
            "powerline_path_bg": self.pl_path_bg.currentData() or "",
        }
