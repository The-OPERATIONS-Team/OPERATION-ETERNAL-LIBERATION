"""Saves tab: hosts the Save Editor and Backup / Restore as inner tabs."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from views.save_editor_tab import SaveEditorTab
from views.backup_restore_tab import BackupRestoreTab


class SavesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        inner = QTabWidget()
        self.editor_tab = SaveEditorTab()
        inner.addTab(self.editor_tab, "Save Editor")
        self.backup_tab = BackupRestoreTab()
        inner.addTab(self.backup_tab, "Backup / Restore")
        layout.addWidget(inner)
