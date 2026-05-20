"""Process management for gameserver, RPCN, and RPCS3.

Supports two launch modes:
  - new_console=False (default): QProcess, inherits parent's console state.
  - new_console=True: subprocess.Popen with CREATE_NEW_CONSOLE so the child
    gets its own visible CMD window.  State is polled every 2 s via QTimer.
"""
import socket
import subprocess
import sys
import platform

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

PLATFORM = platform.system()

def is_port_open(host: str = "127.0.0.1", port: int = 80, timeout: float = 0.4) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout seconds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class ManagedProcess(QObject):
    """Wraps either QProcess or subprocess.Popen for a single named child process."""

    started = Signal()
    stopped = Signal(int)  # exit code

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name   = name
        self._proc: QProcess | None          = None
        self._popen: subprocess.Popen | None = None
        self._poll_timer: QTimer | None      = None

    def launch(
        self,
        program: str,
        args: list[str],
        cwd: str | None = None,
        new_console: bool = False,
        elevate: bool = False,
    ) -> bool:
        """Start the process.  Returns False if already running or failed to start."""
        if self.is_running():
            return False

        if elevate and PLATFORM == 'Linux':
            # darwin is cursed, windows can use powershell but is similarly cursed.
            # you (should not) run Qt6 as root and is impossible under wayland.
            args = [program] + args
            program = "pkexec"

        if new_console and PLATFORM == 'Windows':
            try:
                self._popen = subprocess.Popen(
                    [program] + args,
                    cwd=cwd,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            except OSError:
                return False
            self._poll_timer = QTimer(self)
            self._poll_timer.timeout.connect(self._check_popen)
            self._poll_timer.start(2000)
            self.started.emit()
            return True

        self._proc = QProcess(self)
        if cwd:
            self._proc.setWorkingDirectory(cwd)
        self._proc.finished.connect(self._on_qprocess_finished)
        self._proc.start(program, args)
        if not self._proc.waitForStarted(5000):
            self._proc = None
            return False
        self.started.emit()
        return True

    def stop(self):
        if self._popen:
            self._popen.terminate()
            self._popen = None
            if self._poll_timer:
                self._poll_timer.stop()
                self._poll_timer = None
        if self._proc:
            self._proc.terminate()
            if not self._proc.waitForFinished(3000):
                self._proc.kill()
            self._proc = None

    def is_running(self) -> bool:
        if self._popen:
            return self._popen.poll() is None
        return self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning

    def pid(self) -> int | None:
        if self._popen:
            return self._popen.pid
        if self.is_running():
            return self._proc.processId()
        return None

    # ------------------------------------------------------------------
    def _check_popen(self):
        if self._popen and self._popen.poll() is not None:
            rc = self._popen.returncode or 0
            # Windows exit codes are unsigned 32-bit; reinterpret as signed so
            # Qt's Signal(int) doesn't overflow (e.g. 0xC000013A → -1073741510).
            if rc > 2_147_483_647:
                rc -= 4_294_967_296
            self._popen = None
            if self._poll_timer:
                self._poll_timer.stop()
                self._poll_timer = None
            self.stopped.emit(rc)

    def _on_qprocess_finished(self, exit_code: int, _exit_status):
        self._proc = None
        self.stopped.emit(exit_code)
