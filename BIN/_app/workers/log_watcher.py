"""Game server log watcher."""
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QTimer


class GameServerLogWatcher(QObject):
    """Polls gameserver.log for `ev_save_load_error` (no-save-on-server boot failure)."""

    SAVE_LOAD_ERROR_TOKEN = b"ev_save_load_error"
    POLL_MS = 2000

    save_load_error_seen = Signal()

    def __init__(self, log_path: Path, parent=None):
        super().__init__(parent)
        self._log_path = log_path
        self._pos = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._tick)

    def start(self):
        # Start at EOF; only events written from now on count.
        try:
            self._pos = self._log_path.stat().st_size
        except OSError:
            self._pos = 0
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _tick(self):
        try:
            size = self._log_path.stat().st_size
        except OSError:
            return
        if size < self._pos:
            # Log rotated; restart from the beginning.
            self._pos = 0
        if size <= self._pos:
            return
        try:
            with self._log_path.open("rb") as fh:
                fh.seek(self._pos)
                chunk = fh.read()
        except OSError:
            return
        self._pos += len(chunk)
        if self.SAVE_LOAD_ERROR_TOKEN in chunk:
            self.save_load_error_seen.emit()
