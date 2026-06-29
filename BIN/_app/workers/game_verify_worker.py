"""Per-file verification of the installed game against the manifest."""
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from modules import game_verify


class GameVerifyWorker(QThread):
    done = Signal(object)        # game_verify.VerifyResult
    failed = Signal(str)
    progress = Signal(int, int)  # (file number being hashed, total files)

    def __init__(self, game_dir: Path, param_sfo: Path, entry: dict, parent=None):
        super().__init__(parent)
        self._game_dir = game_dir
        self._param = param_sfo
        self._entry = entry

    def run(self):
        try:
            result = game_verify.verify(
                self._game_dir, self._param, self._entry,
                progress=lambda i, total, rel: self.progress.emit(i + 1, total),
            )
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.done.emit(result)
