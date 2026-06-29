"""Settings tab."""
from PySide6.QtCore import Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QGroupBox, QCheckBox, QComboBox, QPushButton, QMessageBox,
)

from app.paths import VERSION, GITHUB_REPO, RELEASE_CHANNEL
from app.settings import save_settings
from modules.updater import UpdateChecker


class SettingsTab(QWidget):
    saved = Signal(dict)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(10)

        self._tss_url = QLineEdit(self._settings.get("tss_download_url", ""))
        self._tss_url.setPlaceholderText("https://example.com/tss/")
        form.addRow("TSS download URL:", self._tss_url)

        root.addLayout(form)

        upd_grp = QGroupBox("Updates")
        upd_form = QFormLayout(upd_grp)
        upd_form.setSpacing(8)

        self._auto_check = QCheckBox("Check for updates on startup")
        self._auto_check.setChecked(self._settings.get("auto_check_updates", False))
        upd_form.addRow(self._auto_check)

        self._channel_combo = QComboBox()
        self._channel_combo.addItem("Main (stable)",       "main")
        self._channel_combo.addItem("Experimental (pre-release)", "experimental")
        saved_channel = self._settings.get("update_channel", RELEASE_CHANNEL)
        idx = self._channel_combo.findData(saved_channel)
        if idx >= 0:
            self._channel_combo.setCurrentIndex(idx)
        upd_form.addRow("Update channel:", self._channel_combo)

        self._check_now_btn = QPushButton("Check for updates now")
        self._check_now_btn.clicked.connect(self._check_now)
        upd_form.addRow(self._check_now_btn)

        root.addWidget(upd_grp)
        root.addStretch()

        btn_row = QHBoxLayout()
        save_btn  = QPushButton("Save Settings")
        reset_btn = QPushButton("Reset to Defaults")
        btn_row.addWidget(save_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        save_btn.clicked.connect(self._save)
        reset_btn.clicked.connect(self._reset)

    def _check_now(self):
        self._check_now_btn.setEnabled(False)
        self._check_now_btn.setText("Checking...")
        channel = self._channel_combo.currentData()
        checker = UpdateChecker(self)
        checker.update_available.connect(self._on_update_found)
        checker.check_complete.connect(self._on_check_done)
        checker.check(GITHUB_REPO, channel, VERSION)

    def _on_update_found(self, version: str, url: str):
        btn = QMessageBox.question(
            self, "Update available",
            f"Version {version} is available.\nOpen the download page?",
        )
        if btn == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(url))

    def _on_check_done(self):
        self._check_now_btn.setEnabled(True)
        self._check_now_btn.setText("Check for updates now")

    def _save(self):
        self._settings["tss_download_url"] = self._tss_url.text().strip()
        self._settings["auto_check_updates"] = self._auto_check.isChecked()
        self._settings["update_channel"] = self._channel_combo.currentData()
        save_settings(self._settings)
        self.saved.emit(self._settings)
        QMessageBox.information(self, "Saved", "Settings saved.")

    def _reset(self):
        self._tss_url.clear()
