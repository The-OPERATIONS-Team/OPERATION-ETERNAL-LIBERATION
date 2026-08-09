"""The one place this application asks for Administrator or root.

Every privileged action goes through run(), so there is a single implementation to
audit rather than one per feature, and a feature that needs privilege cannot quietly
grow its own way of asking for it.

Two rules hold here, and both are why this is not inlined at the call sites.

No shell is involved. The program is launched directly, so nothing between here and
it re-reads an argument looking for syntax: a path interpolated into a cmd.exe line
is still parsed by cmd, which expands %VAR% even inside quotes. It also means the
prompt names the program actually being run, and a user who is asked to elevate
netsh can see that is what they are approving.

Programs are named by absolute path. Resolving a name through PATH is ordinary for an
unprivileged call and not for this one: whatever is found runs as Administrator or
root.

Pure stdlib, so anything can import it without pulling in the GUI toolkit.
"""
import ntpath
import os
import shlex
import shutil
import subprocess
import sys

GRANTED = "granted"
CANCELLED = "cancelled"
FAILED = "failed"
UNSUPPORTED = "unsupported"


def system32(name: str) -> str:
    """An absolute path to a Windows system executable.

    Joined with ntpath rather than os.path so it builds a Windows path whatever the
    host is, which keeps it the same string under test as it is in front of a player.
    """
    return ntpath.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", name)


def available() -> bool:
    """Whether a privilege prompt can be raised on this desktop at all."""
    if sys.platform == "win32":
        return True  # UAC is always the prompt; there is nothing to look for
    return _linux_wrapper(["true"]) is not None


def run(commands, timeout: int = 120) -> str:
    """Run each argv in turn as Administrator or root, behind one prompt.

    commands is a sequence of argv sequences. They run in order and stop at the
    first failure, so a repair cannot half-apply without saying so.

    Windows prompts once per command, because each is launched as its own elevated
    program rather than sequenced by a shell. Callers should ask for as few as the
    job needs. Linux prompts once, since polkit sequences them behind one password.

    Returns "granted", "cancelled" (the prompt was dismissed), "failed", or
    "unsupported". Re-check the thing you changed afterwards; a granted prompt
    means the commands ran, not that they did what you wanted.
    """
    commands = [list(c) for c in commands]
    if not commands:
        return GRANTED
    if sys.platform == "win32":
        return _run_windows(commands, timeout)
    if sys.platform.startswith("linux"):
        return _run_linux(commands, timeout)
    return UNSUPPORTED


# --- Windows ----------------------------------------------------------------

def _quote(arg: str) -> str:
    """One argument for a Windows command line.

    Windows forbids '"' in a path and none of these arguments are built from
    anything but paths and literals, so the backslash-before-quote rule cannot
    arise. Rather than assume that, an argument carrying a quote is refused: it
    would be the one case where quoting here could be escaped.
    """
    if '"' in arg:
        raise ValueError("argument contains a quote")
    return f'"{arg}"' if (arg == "" or " " in arg or "\t" in arg) else arg


def _run_windows(commands, timeout: int) -> str:
    for argv in commands:
        try:
            parameters = " ".join(_quote(str(a)) for a in argv[1:])
        except ValueError:
            return FAILED
        outcome = _elevate_windows(str(argv[0]), parameters, timeout)
        if outcome != GRANTED:
            return outcome
    return GRANTED


def _elevate_windows(program: str, parameters: str, timeout: int) -> str:
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NO_CONSOLE = 0x00008000
    ERROR_CANCELLED = 1223
    WAIT_TIMEOUT = 0x00000102

    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
    info.lpVerb = "runas"
    info.lpFile = program
    info.lpParameters = parameters
    info.nShow = 0  # SW_HIDE
    try:
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            return CANCELLED if ctypes.GetLastError() == ERROR_CANCELLED else FAILED
        if not info.hProcess:
            return GRANTED
        waited = ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, timeout * 1000)
        if waited == WAIT_TIMEOUT:
            ctypes.windll.kernel32.CloseHandle(info.hProcess)
            return FAILED
        code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
        return GRANTED if code.value == 0 else FAILED
    except OSError:
        return FAILED


# --- Linux ------------------------------------------------------------------

def _linux_wrapper(argv):
    """argv wrapped to run as root through the desktop's password prompt.

    pkexec where available; systemd-run otherwise, which reaches the same polkit
    agent, because Debian ships pkexec in a package KDE does not pull in.
    """
    pkexec = shutil.which("pkexec")
    if pkexec:
        return [pkexec] + argv
    systemd_run = shutil.which("systemd-run")
    if systemd_run:
        return [systemd_run, "--quiet", "--wait", "--collect"] + argv
    return None


def _run_linux(commands, timeout: int) -> str:
    if len(commands) == 1:
        payload = commands[0]
    else:
        # More than one command needs a shell to sequence them under a single
        # prompt. Every argument is quoted, so the shell sees data, not syntax.
        script = " && ".join(" ".join(shlex.quote(str(a)) for a in argv) for argv in commands)
        payload = ["/bin/sh", "-c", script]
    argv = _linux_wrapper(payload)
    if not argv:
        return UNSUPPORTED
    try:
        res = subprocess.run(argv, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return FAILED
    if res.returncode == 0:
        return GRANTED
    # pkexec reports a dismissed prompt as 126. systemd-run has no distinct code,
    # so a cancel there is indistinguishable from a failure and reports as one.
    return CANCELLED if res.returncode == 126 else FAILED
