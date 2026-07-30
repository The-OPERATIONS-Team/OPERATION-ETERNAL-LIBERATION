"""Main window: tab assembly, signal wiring, and startup hooks.

Orchestration of the launch sequence and process lifecycle lives in
LaunchController.
"""
import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QVBoxLayout, QMessageBox,
)

from app.paths import _IS_WIN, _IS_MAC, ROOT_DIR, VERSION
from app.settings import load_settings, save_settings
from views.play_tab import PlayTab
from views.saves_tab import SavesTab
from views.tss_tab import TssTab
from views.settings_tab import SettingsTab
from viewmodels.launch_controller import LaunchController


class ACILauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings = load_settings()

        self.setWindowTitle(f"OPERATION ETERNAL LIBERATION {VERSION}")
        self.setFixedSize(720, 660)
        self._build_ui()

        self._controller = LaunchController(self, self._settings)
        self._play_tab.launch_requested.connect(self._controller.start_launch)
        self._saves_tab.backup_tab.restore_staged.connect(self._controller.mark_restore_staged)
        self._saves_tab.editor_tab.restore_staged.connect(self._controller.mark_restore_staged)
        self._saves_tab.editor_tab.set_game_running_check(self._controller.rpcs3_is_running)

        # One-shot WireGuard relay bind check, once the window is shown.
        QTimer.singleShot(0, self._play_tab._check_relay_bind)

        # Let the window paint before the first save-state checks.
        QTimer.singleShot(800, self._controller.check_save_alerts)

        if self._settings.get("auto_check_updates"):
            QTimer.singleShot(1500, self._controller.check_for_updates_startup)

        if (not _IS_WIN and not _IS_MAC
                and not self._settings.get("desktop_shortcut_offered")):
            QTimer.singleShot(1200, self._offer_desktop_shortcut)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        self._play_tab = PlayTab(self._settings)
        self._saves_tab = SavesTab()
        self._tss_tab   = TssTab(self._settings)
        self._settings_tab = SettingsTab(self._settings)

        tabs.addTab(self._play_tab,     "Play")
        tabs.addTab(self._saves_tab,    "Saves")
        tabs.addTab(self._tss_tab,      "TSS Files")
        tabs.addTab(self._settings_tab, "Settings")
        layout.addWidget(tabs)

        self._settings_tab.saved.connect(self._on_settings_saved)

    def _offer_desktop_shortcut(self):
        """One-time Linux equivalent of the installer's desktop shortcut."""
        self._settings["desktop_shortcut_offered"] = True
        save_settings(self._settings)
        play = ROOT_DIR / "Play OPERATION ETERNAL LIBERATION (Linux).sh"
        if not play.exists():
            return
        if QMessageBox.question(
                self, "Application menu entry",
                "Add OPERATION ETERNAL LIBERATION to your application menu?",
        ) != QMessageBox.StandardButton.Yes:
            return
        apps_dir = Path(os.environ.get("XDG_DATA_HOME")
                        or os.path.join(os.environ.get("HOME", "."), ".local", "share")) / "applications"
        try:
            apps_dir.mkdir(parents=True, exist_ok=True)
            (apps_dir / "operation-eternal-liberation.desktop").write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=OPERATION ETERNAL LIBERATION\n"
                "Comment=Community multiplayer launcher\n"
                f'Exec="{play}"\n'
                f'Path={ROOT_DIR}\n'
                "Terminal=false\n"
                "Categories=Game;\n",
                encoding="utf-8",
            )
        except OSError as e:
            QMessageBox.warning(self, "Application menu entry",
                                f"Could not create the menu entry: {e}")

    def _on_settings_saved(self, settings: dict):
        self._settings = settings
        self._tss_tab._settings = settings

    def closeEvent(self, event):
        self._controller.shutdown()
        super().closeEvent(event)
