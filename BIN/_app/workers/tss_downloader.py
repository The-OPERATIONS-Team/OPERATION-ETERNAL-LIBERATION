"""Async TSS file downloader over QNetworkAccessManager."""
import os

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from modules import tss as tss_mod


class TssDownloader(QObject):
    progress    = Signal(int, int, str)  # (done, total, filename)
    finished    = Signal(list)           # list of error strings

    def __init__(self, base_url: str, dest_dir: str, parent=None):
        super().__init__(parent)
        self._base_url  = base_url.rstrip("/")
        self._dest_dir  = dest_dir
        self._nam       = QNetworkAccessManager(self)
        self._pending   = list(tss_mod.TSS_FILES)
        self._done      = 0
        self._errors: list[str] = []
        self._current_reply: QNetworkReply | None = None

    def start(self):
        self._fetch_next()

    def _fetch_next(self):
        if not self._pending:
            self.finished.emit(self._errors)
            return
        name = self._pending[0]
        url  = f"{self._base_url}/{name}"
        req  = QNetworkRequest(QUrl(url))
        self._current_reply = self._nam.get(req)
        self._current_reply.finished.connect(lambda: self._on_reply(name))

    def _on_reply(self, name: str):
        reply = self._current_reply
        self._pending.pop(0)
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            dest = os.path.join(self._dest_dir, name)
            with open(dest, "wb") as f:
                f.write(bytes(data))
        else:
            self._errors.append(f"{name}: {reply.errorString()}")
        reply.deleteLater()
        self._done += 1
        self.progress.emit(self._done, len(tss_mod.TSS_FILES), name)
        self._fetch_next()
