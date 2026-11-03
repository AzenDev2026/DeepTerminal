"""Settings dialog for DeepTerminal."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase, QFontInfo
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
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .config import DEFAULTS, Config, theme_names
from .shells import shell_choices


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
        self.setMinimumWidth(560)
        self._build()

    # -- construction ----------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.shell_combo = QComboBox()
        for key, label, availability in shell_choices():
            self.shell_combo.addItem(label, key)
            self.shell_combo.setItemData(self.shell_combo.count() - 1, availability, Qt.ItemDataRole.ToolTipRole)
        current_shell = self.config.get_str("shell")
        index = self.shell_combo.findData(current_shell)
        self.shell_combo.setCurrentIndex(max(0, index))
        self.shell_combo.currentIndexChanged.connect(self._sync_custom_enabled)
        form.addRow("Default shell:", self.shell_combo)

        self.custom_edit = QLineEdit(self.config.get_str("custom_shell"))
        self.custom_edit.setPlaceholderText("e.g. fish -i  ·  /bin/zsh -l  ·  nu")
        form.addRow("Custom command:", self.custom_edit)

        self.prompt_edit = QLineEdit(self.config.get_str("prompt"))
        self.prompt_edit.setPlaceholderText("DT ({path})::: ")
        self.prompt_edit.setToolTip("PowerShell and Bash only. {path} is replaced with the current directory.")
        form.addRow("Prompt format:", self.prompt_edit)

        self.startup_edit = QLineEdit(self.config.get_str("startup_cmd"))
        self.startup_edit.setPlaceholderText("Command typed into every new tab (optional)")
        form.addRow("Startup command:", self.startup_edit)

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

        working_row = QHBoxLayout()
        self.working_edit = QLineEdit(self.config.get_str("working_dir"))
        self.working_edit.setPlaceholderText("Default: home directory")
        working_row.addWidget(self.working_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_directory)
        working_row.addWidget(browse)
        form.addRow("Start directory:", working_row)

        layout.addLayout(form)

        note = QLabel(
            "Shell, prompt and startup command apply to <b>new tabs</b>. "
            "Theme, font and cursor blink apply immediately."
        )
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.RichText)
        note.setStyleSheet("color: palette(mid);")
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        restore = buttons.addButton("Restore Defaults", QDialogButtonBox.ButtonRole.ResetRole)
        restore.clicked.connect(self._restore_defaults)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.addButton(QDialogButtonBox.StandardButton.Ok)
        ok.setDefault(True)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._sync_custom_enabled()

    # -- behaviour -------------------------------------------------------
    def _sync_custom_enabled(self) -> None:
        self.custom_edit.setEnabled(self.shell_combo.currentData() == "custom")

    def _browse_directory(self) -> None:
        current = self.working_edit.text().strip() or self.config.working_dir()
        chosen = QFileDialog.getExistingDirectory(self, "Start directory", current)
        if chosen:
            self.working_edit.setText(chosen)

    def _restore_defaults(self) -> None:
        self.shell_combo.setCurrentIndex(max(0, self.shell_combo.findData(DEFAULTS["shell"])))
        self.custom_edit.setText(str(DEFAULTS["custom_shell"]))
        self.prompt_edit.setText(str(DEFAULTS["prompt"]))
        self.startup_edit.setText(str(DEFAULTS["startup_cmd"]))
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(DEFAULTS["theme"])))
        self.font_combo.setCurrentIndex(0)
        self.font_size.setValue(int(DEFAULTS["font_size"]))
        self.scrollback.setValue(int(DEFAULTS["scrollback"]))
        self.blink.setChecked(bool(DEFAULTS["cursor_blink"]))
        self.working_edit.setText(str(DEFAULTS["working_dir"]))
        self._sync_custom_enabled()

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
            "prompt": self.prompt_edit.text(),
            "startup_cmd": self.startup_edit.text(),
            "theme": self.theme_combo.currentData(),
            "font_family": self.font_combo.currentData() or "",
            "font_size": self.font_size.value(),
            "scrollback": self.scrollback.value(),
            "cursor_blink": self.blink.isChecked(),
            "working_dir": self.working_edit.text().strip(),
        }
