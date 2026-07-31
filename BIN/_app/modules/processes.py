"""Process management for gameserver, RPCN, and RPCS3.

Supports two launch modes:
  - new_console=False (default): QProcess, inherits parent's console state.
  - new_console=True: the child gets its own visible console window.  On
    Windows that is subprocess.Popen with CREATE_NEW_CONSOLE; on Linux the
    child is wrapped in the first terminal emulator found (hidden QProcess
    fallback when none is installed).  State is polled every 2 s via QTimer.
"""
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import uuid

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

# Terminal emulators probed in order. All but gnome-terminal keep the spawned
# command in our process group, so killpg in stop() reaches it. gnome-terminal
# delegates to a server process; --wait keeps our handle alive for the child's
# lifetime, but the window survives stop() (the child is reaped by the server).
_LINUX_TERMINALS = [
    ("konsole",             lambda prog, args: ["konsole", "-e", prog, *args]),
    ("xfce4-terminal",      lambda prog, args: ["xfce4-terminal", "-x", prog, *args]),
    ("kitty",               lambda prog, args: ["kitty", prog, *args]),
    ("alacritty",           lambda prog, args: ["alacritty", "-e", prog, *args]),
    ("foot",                lambda prog, args: ["foot", prog, *args]),
    ("xterm",               lambda prog, args: ["xterm", "-e", prog, *args]),
    ("x-terminal-emulator", lambda prog, args: ["x-terminal-emulator", "-e", prog, *args]),
    ("gnome-terminal",      lambda prog, args: ["gnome-terminal", "--wait", "--", prog, *args]),
]


def _terminal_argv(program: str, args: list[str]) -> list[str] | None:
    """Wrap program+args in an available terminal emulator, or None if none found."""
    for name, build in _LINUX_TERMINALS:
        if shutil.which(name):
            return build(program, list(args))
    return None


def is_port_open(host: str = "127.0.0.1", port: int = 80, timeout: float = 0.4) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout seconds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_BIND_PROBE = """
import errno, socket, sys
rc = 0
for port in (80, 443):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((sys.argv[1], port))
    except OSError as e:
        rc = 2 if e.errno in (errno.EACCES, errno.EPERM) else rc
    finally:
        s.close()
sys.exit(rc)
"""


def needs_port_privilege(python_exe: str, host: str) -> bool:
    """Return True if python_exe is denied ports 80/443 on host for lack of
    privilege (Linux <1024 restriction).

    Runs the probe in the given interpreter because a file capability
    (cap_net_bind_service on the gameserver python) is per-binary; testing
    from the launcher process would report the wrong privilege. Non-privilege
    bind failures return False so the gameserver's own error reporting shows
    them.
    """
    try:
        res = subprocess.run(
            [python_exe, "-c", _BIND_PROBE, host],
            capture_output=True, timeout=10,
        )
        return res.returncode == 2
    except (OSError, subprocess.TimeoutExpired):
        return False


def _elevation_argv(command: list[str]) -> list[str] | None:
    """Wrap command so it runs as root after the desktop password prompt.
    pkexec where available; systemd-run otherwise (same polkit agent, but
    Debian ships pkexec as a separate package KDE does not pull in)."""
    pkexec = shutil.which("pkexec")
    if pkexec:
        return [pkexec] + command
    systemd_run = shutil.which("systemd-run")
    if systemd_run:
        return [systemd_run, "--quiet", "--wait", "--collect"] + command
    return None


def can_elevate() -> bool:
    """Return True if a graphical privilege prompt is available."""
    return _elevation_argv(["true"]) is not None


def grant_port_capability(python_exe: str) -> str:
    """Grant cap_net_bind_service to python_exe through the desktop's own
    password prompt. Needs a running polkit agent (standard on desktops).

    Returns "granted", "cancelled" (user dismissed the prompt), or "failed".
    """
    setcap = next((p for p in (shutil.which("setcap"), "/usr/sbin/setcap",
                               "/sbin/setcap") if p and os.path.exists(p)), None)
    if not setcap:
        return "failed"
    argv = _elevation_argv([setcap, "cap_net_bind_service=+ep", python_exe])
    if not argv:
        return "failed"
    try:
        res = subprocess.run(argv, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return "failed"
    if res.returncode == 0:
        return "granted"
    # pkexec reports a dismissed prompt as 126; systemd-run gives no
    # distinct code, so a cancel there surfaces as "failed".
    return "cancelled" if res.returncode == 126 else "failed"


def launch_macos_privileged(
    program: str,
    args: list[str],
    cwd: str,
    watch_pid: int,
) -> bool:
    """Start the game server through the native macOS administrator prompt.

    The child redirects its inherited descriptors so ``osascript`` can return
    immediately. ``--watch-pid`` makes the elevated server stop when the
    launcher process exits.
    """
    if sys.platform != "darwin":
        return False

    del cwd  # launchctl starts the script by absolute path.
    log_path = f"/tmp/oel-gameserver-{os.getuid()}.log"
    label = f"community.operations-team.oel.gameserver.{watch_pid}.{uuid.uuid4().hex[:8]}"
    argv = [program, *args, "--watch-pid", str(watch_pid)]
    launch_argv = [
        "/bin/launchctl", "submit",
        "-l", label,
        "-o", log_path,
        "-e", log_path,
        "--", *argv,
    ]
    command = " ".join(shlex.quote(item) for item in launch_argv)
    try:
        result = subprocess.run(
            [
                "/usr/bin/osascript",
                "-e", "on run argv",
                "-e", "do shell script (item 1 of argv) with administrator privileges",
                "-e", "end run",
                "--", command,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def ensure_gameserver_certificate(python_exe: str, cwd: str) -> bool:
    """Generate the local TLS files as the current, non-privileged user."""
    try:
        result = subprocess.run(
            [
                python_exe,
                "-c",
                "import opeternal_listener as server; server.ensure_cert()",
            ],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


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
    ) -> bool:
        """Start the process.  Returns False if already running or failed to start."""
        if self.is_running():
            return False

        if new_console:
            if sys.platform == "win32":
                try:
                    self._popen = subprocess.Popen(
                        [program] + args,
                        cwd=cwd,
                        creationflags=subprocess.CREATE_NEW_CONSOLE,
                    )
                except OSError:
                    return False
                return self._start_popen_polling()

            argv = _terminal_argv(program, args)
            if argv is not None:
                # Own process group so stop() can signal the terminal and the
                # wrapped child together.
                try:
                    self._popen = subprocess.Popen(
                        argv,
                        cwd=cwd,
                        start_new_session=True,
                    )
                except OSError:
                    return False
                return self._start_popen_polling()
            # No terminal emulator (e.g. Steam Deck game mode): fall through
            # to a hidden QProcess; the log watcher still surfaces status.

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
            if sys.platform != "win32":
                try:
                    os.killpg(os.getpgid(self._popen.pid), signal.SIGTERM)
                except OSError:
                    self._popen.terminate()
            else:
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
    def _start_popen_polling(self) -> bool:
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._check_popen)
        self._poll_timer.start(2000)
        self.started.emit()
        return True

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
