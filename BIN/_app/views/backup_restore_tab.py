"""Backup / Restore sub-tab."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QMessageBox,
)

from app.paths import PORTABLE_DIR, APP_DIR, RPCN_YML
from modules import tus_saves


class BackupRestoreTab(QWidget):
    restore_staged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[tus_saves.BackupEntry] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        path_row = QHBoxLayout()
        self._tus_label = QLabel()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(80)
        path_row.addWidget(QLabel("TUS folder:"))
        path_row.addWidget(self._tus_label, 1)
        path_row.addWidget(refresh_btn)
        root.addLayout(path_row)
        refresh_btn.clicked.connect(self._refresh)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Date", "Time", "Slot", "Size"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._tree, 1)

        btn_row = QHBoxLayout()
        self._restore_btn  = QPushButton("Restore Selected")
        self._newgame_btn  = QPushButton("New Game Override")
        btn_row.addWidget(self._restore_btn)
        btn_row.addWidget(self._newgame_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        note = QLabel(
            "Restore: stages selected backup(s), takes effect on next game boot.\n"
            "New Game Override: resets all slots so the game offers a fresh start."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        self._restore_btn.clicked.connect(self._restore_selected)
        self._newgame_btn.clicked.connect(self._new_game_override)

        self._refresh()

    def _tus_root(self) -> str:
        return str(PORTABLE_DIR / "tus")

    def _refresh(self):
        tus_root = self._tus_root()
        short = Path(tus_root).relative_to(APP_DIR.parent) if APP_DIR.parent in Path(tus_root).parents else Path(tus_root)
        self._tus_label.setText(str(short))
        self._tree.clear()
        self._entries = tus_saves.list_backups(tus_root)

        sessions: dict[str, QTreeWidgetItem] = {}
        for entry in self._entries:
            if entry.session not in sessions:
                parent = QTreeWidgetItem(self._tree, [entry.date, entry.time[:5], "", ""])
                f = parent.font(0)
                f.setBold(True)
                parent.setFont(0, f)
                parent.setExpanded(True)
                sessions[entry.session] = parent
            else:
                parent = sessions[entry.session]

            child = QTreeWidgetItem(parent, [
                "", entry.time, entry.slot, f"{entry.size_kb} KB"
            ])
            child.setCheckState(0, Qt.CheckState.Unchecked)
            child.setData(0, Qt.ItemDataRole.UserRole, entry)

        # Allow clicking session header to toggle all children
        self._tree.itemClicked.connect(self._session_click)

    def _session_click(self, item: QTreeWidgetItem, _col: int):
        if item.childCount() == 0:
            return  # leaf
        # Toggle all children to opposite of majority state
        checked = sum(
            1 for i in range(item.childCount())
            if item.child(i).checkState(0) == Qt.CheckState.Checked
        )
        new_state = Qt.CheckState.Unchecked if checked > item.childCount() // 2 else Qt.CheckState.Checked
        for i in range(item.childCount()):
            item.child(i).setCheckState(0, new_state)

    def _collect_checked(self) -> list[tus_saves.BackupEntry]:
        result = []
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            parent = root.child(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    entry = child.data(0, Qt.ItemDataRole.UserRole)
                    result.append(entry)
        return result

    def _restore_selected(self):
        entries = self._collect_checked()
        if not entries:
            QMessageBox.information(self, "Nothing selected", "Check the backups you want to restore.")
            return
        errors = [e for entry in entries for e in [tus_saves.stage_restore(entry)] if e]
        if errors:
            QMessageBox.warning(self, "Restore errors", "\n".join(errors))
        else:
            self.restore_staged.emit()
            QMessageBox.information(
                self, "Staged",
                f"{len(entries)} slot(s) staged for restore.\n\n"
                "Boot OPERATION ETERNAL LIBERATION. RPCS3 will apply the backup automatically.\n"
                "Save in-game to commit the restored data back to RPCN."
            )

    def _new_game_override(self):
        reply = QMessageBox.question(
            self, "New Game Override",
            "This will create temporary files for all known save slots.\n"
            "On next boot, the game will report no save data and offer a fresh start.\n\n"
            "Your cloud save on RPCN is NOT deleted. It will be overwritten only if you save in-game.\n\n"
            "Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        staged, errors = tus_saves.stage_new_game(self._tus_root(), str(RPCN_YML))
        if errors:
            QMessageBox.warning(self, "Errors", "\n".join(errors))
        else:
            self.restore_staged.emit()
            QMessageBox.information(
                self, "Done",
                f"{staged} slot(s) staged.\nBoot OP ETERNAL to start fresh."
            )
