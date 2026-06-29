"""Play tab view model: setup-status polling, edition detection,
verification orchestration, and launch gating.
"""
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, QTimer

from app.paths import GAME_MANIFEST, FIRMWARE_INDICATOR, GAME_BASE_DIR, TSS_SRC_DIR
from modules import games, tss as tss_mod, game_verify
from workers.game_verify_worker import GameVerifyWorker


@dataclass
class SetupStatus:
    fw_ok: bool
    game: str            # "missing" | "unsupported" | "ok"
    region: str
    tss_present: int
    tss_total: int


class PlayViewModel(QObject):
    setup_status    = Signal(object)      # SetupStatus
    verify_started  = Signal()
    verify_progress = Signal(int, int)    # (file number being hashed, total files)
    verify_finished = Signal(object)      # game_verify.VerifyResult
    verify_failed   = Signal(str)         # error message

    # launch_decision() outcomes
    LAUNCH_OK                = "ok"
    LAUNCH_UNSUPPORTED       = "unsupported"
    LAUNCH_VERIFY_UNFINISHED = "verify_unfinished"
    LAUNCH_VERIFY_FAILED     = "verify_failed"
    LAUNCH_VERIFY_ERROR      = "verify_error"

    POLL_MS = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manifest = game_verify.load_manifest(GAME_MANIFEST)
        self._verify_worker: GameVerifyWorker | None = None
        self._verify_result = None
        self._verify_error = False
        # Re-verify only after a changed signature has held for one poll, so an
        # install still being written is not hashed mid-write.
        self._verify_signature = None
        self._pending_signature = None
        self._game_hash = ""
        self._unsupported_profile = None
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self.refresh)

    def start_polling(self):
        self._timer.start()

    def refresh(self):
        fw_ok   = FIRMWARE_INDICATOR.exists()
        profile = games.find_installed(GAME_BASE_DIR)
        n       = tss_mod.count_present(str(TSS_SRC_DIR))
        total   = len(tss_mod.TSS_FILES)

        self._unsupported_profile = profile if (profile and not profile.supported) else None
        if profile is None:
            game, region = "missing", ""
        elif not profile.supported:
            game, region = "unsupported", profile.region
        else:
            game, region = "ok", ""
            self._maybe_start_verification(profile)

        self.setup_status.emit(SetupStatus(fw_ok, game, region, n, total))

    def _maybe_start_verification(self, profile):
        if self._verify_worker is not None:
            return
        sig = self._install_signature(profile)
        if sig == self._verify_signature:
            self._pending_signature = sig
            return
        if sig != self._pending_signature:
            # First poll at a new signature: wait one more to let the install settle.
            self._pending_signature = sig
            return
        self._start_verification(profile, sig)

    def force_verify(self):
        """Re-run verification now, ignoring the change check (manual retry)."""
        if self._verify_worker is not None:
            return
        profile = games.find_installed(GAME_BASE_DIR)
        if profile is None or not profile.supported:
            return
        self._start_verification(profile, self._install_signature(profile))

    def _install_signature(self, profile) -> str:
        game_dir = GAME_BASE_DIR / profile.title_id
        return game_verify.install_signature(game_dir, game_dir / "PARAM.SFO")

    def _start_verification(self, profile, sig):
        self._verify_signature = sig
        self._pending_signature = sig
        self._verify_result = None
        self._verify_error = False
        self._game_hash = ""
        game_dir = GAME_BASE_DIR / profile.title_id
        entry = game_verify.game_entry(self._manifest, profile.title_id)
        self.verify_started.emit()
        self._verify_worker = GameVerifyWorker(game_dir, game_dir / "PARAM.SFO", entry, self)
        self._verify_worker.progress.connect(self.verify_progress)
        self._verify_worker.done.connect(self._on_verify_done)
        self._verify_worker.failed.connect(self._on_verify_failed)
        self._verify_worker.start()

    def _clear_verify_worker(self):
        if self._verify_worker is not None:
            self._verify_worker.deleteLater()
            self._verify_worker = None

    def _on_verify_done(self, result):
        self._clear_verify_worker()
        self._verify_result = result
        self._game_hash = game_verify.fingerprint(result)
        self.verify_finished.emit(result)

    def _on_verify_failed(self, error: str):
        self._clear_verify_worker()
        self._verify_error = True
        self.verify_failed.emit(error)

    @property
    def verify_result(self):
        return self._verify_result

    @property
    def verify_running(self) -> bool:
        return self._verify_worker is not None

    @property
    def verify_errored(self) -> bool:
        return self._verify_error

    def get_game_hash(self) -> str:
        return self._game_hash

    def launch_decision(self) -> str:
        if self._unsupported_profile is not None:
            return self.LAUNCH_UNSUPPORTED
        if self._verify_result is None:
            if self._verify_worker is not None:
                return self.LAUNCH_VERIFY_UNFINISHED
            if self._verify_error:
                return self.LAUNCH_VERIFY_ERROR
            return self.LAUNCH_OK
        if not self._verify_result.ok:
            return self.LAUNCH_VERIFY_FAILED
        return self.LAUNCH_OK
