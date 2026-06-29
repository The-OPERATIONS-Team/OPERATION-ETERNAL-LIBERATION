"""TSS Files tab."""
import glob
import os
import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QProgressBar,
    QFileDialog, QMessageBox,
)

from app.paths import TSS_SRC_DIR
from modules import games, tss as tss_mod
from workers.tss_downloader import TssDownloader


class TssTab(QWidget):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings   = settings
        self._downloader: TssDownloader | None = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        root.addWidget(QLabel("TSS source folder: " + str(TSS_SRC_DIR)))

        self._list = QTreeWidget()
        self._list.setHeaderLabels(["File", "Status"])
        self._list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        self._dl_btn     = QPushButton("Download Missing")
        self._browse_btn = QPushButton("Copy from Folder...")
        btn_row.addWidget(self._dl_btn)
        btn_row.addWidget(self._browse_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status_lbl = QLabel("")
        root.addWidget(self._status_lbl)

        self._dl_btn.clicked.connect(self._start_download)
        self._browse_btn.clicked.connect(self._browse_and_copy)

        self.refresh()

    def refresh(self):
        self._list.clear()
        for name, present in tss_mod.list_status(str(TSS_SRC_DIR)):
            item = QTreeWidgetItem(self._list, [name, "✓ present" if present else "✗ missing"])
            item.setForeground(1, Qt.GlobalColor.darkGreen if present else Qt.GlobalColor.red)

    def _start_download(self):
        url = self._settings.get("tss_download_url", "").strip()
        if not url:
            QMessageBox.warning(
                self, "No download URL",
                "Configure the TSS download URL in the Settings tab first."
            )
            return
        os.makedirs(str(TSS_SRC_DIR), exist_ok=True)
        self._dl_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(tss_mod.TSS_FILES))
        self._progress.setValue(0)
        self._downloader = TssDownloader(url, str(TSS_SRC_DIR), self)
        self._downloader.progress.connect(self._on_dl_progress)
        self._downloader.finished.connect(self._on_dl_finished)
        self._downloader.start()

    def _on_dl_progress(self, done: int, total: int, name: str):
        self._progress.setValue(done)
        self._status_lbl.setText(f"Downloading... {done}/{total}  ({name})")

    def _on_dl_finished(self, errors: list[str]):
        self._dl_btn.setEnabled(True)
        self._progress.setVisible(False)
        self.refresh()
        if errors:
            QMessageBox.warning(self, "Download errors", "\n".join(errors))
        else:
            self._status_lbl.setText("All TSS files downloaded.")

    def _browse_and_copy(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder containing TSS files")
        if not folder:
            return
        files = glob.glob(os.path.join(folder, f"{games.ACTIVE.comm_id}-*.tss"))
        if not files:
            QMessageBox.warning(self, "No TSS files found",
                                "No .tss files found in that folder.")
            return
        os.makedirs(str(TSS_SRC_DIR), exist_ok=True)
        for f in files:
            shutil.copy2(f, str(TSS_SRC_DIR))
        self.refresh()
        self._status_lbl.setText(f"Copied {len(files)} file(s).")
