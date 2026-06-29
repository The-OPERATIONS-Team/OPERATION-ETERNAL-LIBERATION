"""
RPCS3 log telemetry streamer for -OPERATIONS- mode.

Opt-in only. Tails the live RPCS3 log, scrubs PII (home path, install root,
coherent IP pseudonymization), zlib-compresses in 5-minute chunks, and POSTs
to the telemetry endpoint. On stop(), does a final read-to-EOF and sends a
closing chunk with X-OEL-Final: 1. Failed POSTs are retried up to 3 times
before being dropped; the streamer never blocks or crashes the launcher.
"""

import base64
import hashlib
import http.client
import io
import zlib
import os
import re
import ssl
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from . import hash_util

# SHA-256 of SPKI (DER-encoded public key), base64. Compute with openssl after
# first deploy (see WORK/telemetry-server/README.md). Empty = pinning disabled.
_SPKI_PIN = "1OIpFlvFHYziFx6B7uFO/JZ0rwnC8lXA5bOEhYFE0do="

# Fixed salt for coherent IP pseudonymization across chunks/sessions/uploaders.
# Same real IP always maps to the same token (correlatable but not reversible
# without brute force, acceptable for opt-in diagnostics).
_SALT = b"OEL-telemetry-2026"

_IP_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")

_FLUSH_SECS   = 300
_POST_RETRIES = 3
_POST_RETRY_DELAY = 5  # seconds between retries


def _open_shared(path: Path):
    """Open path for reading while allowing other processes to hold a write lock.

    On Windows, plain open() may fail when RPCS3 holds an exclusive write lock
    on its log file. CreateFileW with FILE_SHARE_WRITE bypasses that.
    Falls back to plain open() on non-Windows.
    """
    if sys.platform == "win32":
        import ctypes
        import msvcrt
        GENERIC_READ          = 0x80000000
        FILE_SHARE_READ       = 0x00000001
        FILE_SHARE_WRITE      = 0x00000002
        FILE_SHARE_DELETE     = 0x00000004
        OPEN_EXISTING         = 3
        FILE_ATTRIBUTE_NORMAL = 0x00000080
        handle = ctypes.windll.kernel32.CreateFileW(
            str(path),
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
        )
        if ctypes.cast(handle, ctypes.c_void_p).value == ctypes.c_size_t(-1).value:
            raise PermissionError(f"CreateFileW failed for {path}")
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        return io.open(fd, "rb")
    return path.open("rb")


def _pseudo_ip(ip: str, cache: dict) -> str:
    if ip not in cache:
        digest = hashlib.sha256(_SALT + ip.encode()).hexdigest()[:8]
        cache[ip] = f"ip-{digest}"
    return cache[ip]


# ---------------------------------------------------------------------------
# SPKI pin verification
# ---------------------------------------------------------------------------

def _check_spki_pin(der_cert: bytes) -> None:
    """Raise ValueError if the peer cert's SPKI hash doesn't match _SPKI_PIN."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    cert = x509.load_der_x509_certificate(der_cert)
    spki = cert.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    got = base64.b64encode(hashlib.sha256(spki).digest()).decode()
    if got != _SPKI_PIN:
        raise ValueError(f"SPKI pin mismatch (got {got!r})")


# ---------------------------------------------------------------------------
# Scrubbing
# ---------------------------------------------------------------------------

class _Scrubber:
    def __init__(self, app_root: str, version: str = ""):
        import getpass
        user = re.escape(getpass.getuser())
        # Windows home path: C:\Users\<name>\  ->  C:\Users\<user>\
        # POSIX home path:   /home/<name>/     ->  /home/<user>/
        self._home_pats = [
            (re.compile(r"(C:\\Users\\)" + user + r"(\\)", re.IGNORECASE), r"\g<1><user>\2"),
            (re.compile(r"(/home/)" + user + r"(/)", re.IGNORECASE),       r"\g<1><user>\2"),
        ]
        self._app_re = (
            re.compile(re.escape(app_root), re.IGNORECASE) if app_root else None
        )
        self._version = version or None
        self._ip_cache: dict[str, str] = {}

    def scrub(self, line: str) -> str:
        for pat, repl in self._home_pats:
            line = pat.sub(repl, line)
        if self._app_re:
            line = self._app_re.sub("<app>", line)
        repl = lambda m: _pseudo_ip(m.group(1), self._ip_cache)
        if self._version and self._version in line:
            return self._version.join(
                _IP_RE.sub(repl, seg) for seg in line.split(self._version)
            )
        return _IP_RE.sub(repl, line)


# ---------------------------------------------------------------------------
# Streamer
# ---------------------------------------------------------------------------

class TelemetryStreamer(threading.Thread):
    """
    Daemon thread that streams a scrubbed, LZMA-compressed RPCS3 log to the
    telemetry endpoint. Call stop() after RPCS3 exits to send the final chunk.
    """

    def __init__(self, log_path: Path, url: str, metadata: dict):
        """
        metadata keys (all optional until populated during run()):
            version, client_id, session_id,
            app_root    -- install root to redact from log lines
            game_usrdir -- Path to USRDIR (hashed for X-OEL-Game-Hash)
            rpcs3_exe   -- Path to rpcs3.exe (hashed for X-OEL-RPCS3-Hash)
        """
        super().__init__(daemon=True, name="TelemetryStreamer")
        self._log_path  = log_path
        self._base_url  = url.rstrip("/")
        self._meta      = dict(metadata)
        self._stop_evt  = threading.Event()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scrubber(self) -> _Scrubber:
        return _Scrubber(self._meta.get("app_root", ""), self._meta.get("version", ""))

    def _post(self, data: bytes, seq: int, final: bool = False):
        headers = {
            "Content-Type":     "application/zlib",
            "Content-Length":   str(len(data)),
            "X-OEL-Session":    self._meta.get("session_id", ""),
            "X-OEL-Seq":        str(seq),
            "X-OEL-Version":    self._meta.get("version", ""),
            "X-OEL-Game-Hash":  self._meta.get("game_hash", ""),
            "X-OEL-RPCS3-Hash": self._meta.get("rpcs3_hash", ""),
            "X-OEL-Client-Id":  self._meta.get("client_id", ""),
        }
        if final:
            headers["X-OEL-Final"] = "1"
        parsed = urllib.parse.urlparse(self._base_url + "/upload")
        for attempt in range(_POST_RETRIES):
            try:
                ctx = ssl.create_default_context()
                conn = http.client.HTTPSConnection(
                    parsed.hostname, parsed.port or 443, context=ctx, timeout=10,
                )
                conn.connect()
                if _SPKI_PIN:
                    _check_spki_pin(conn.sock.getpeercert(binary_form=True))
                conn.request("POST", parsed.path or "/upload", body=data, headers=headers)
                resp = conn.getresponse()
                resp.read()
                conn.close()
                return
            except Exception:
                if attempt < _POST_RETRIES - 1:
                    time.sleep(_POST_RETRY_DELAY)

    def _compress(self, lines: list[bytes]) -> bytes:
        return zlib.compress(b"".join(lines), level=9)

    # ------------------------------------------------------------------
    # Main thread body
    # ------------------------------------------------------------------

    def run(self):
        # Wait for a freshly-written RPCS3.log (mtime >= our start time).
        # The previous session's log already exists on disk; we must wait for
        # RPCS3 to truncate/write it so we open the current session's file.
        t_start = time.time()
        while not self._stop_evt.is_set():
            try:
                if self._log_path.stat().st_mtime >= t_start:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        if self._stop_evt.is_set():
            return

        # Open with shared access so we can read while RPCS3 holds a write lock.
        # Retry for up to 30 s in case RPCS3 hasn't released its open-for-write
        # yet at the exact moment the mtime changed.
        fh = None
        deadline = time.monotonic() + 30
        while fh is None and not self._stop_evt.is_set():
            try:
                fh = _open_shared(self._log_path)
            except OSError:
                if time.monotonic() >= deadline:
                    return
                time.sleep(0.5)
        if fh is None:
            return

        # Hash rpcs3 exe off the UI thread; result goes in headers.
        # game_hash is pre-computed by the game-file verification at launcher
        # init and passed in via metadata.
        try:
            rpcs3_exe = self._meta.get("rpcs3_exe")
            if rpcs3_exe and Path(rpcs3_exe).is_file():
                self._meta["rpcs3_hash"] = hash_util.hash_file(Path(rpcs3_exe))
        except Exception:
            pass

        scrubber   = self._scrubber()
        buf: list[bytes] = []
        seq        = 0
        last_flush = time.monotonic()
        remainder  = b""

        try:
            while not self._stop_evt.is_set():
                raw = fh.read(65536)
                if raw:
                    remainder += raw
                    lines = remainder.split(b"\n")
                    remainder = lines[-1]  # keep the incomplete trailing line
                    for line in lines[:-1]:
                        try:
                            scrubbed = scrubber.scrub(
                                line.decode("utf-8", errors="replace")
                            )
                            buf.append((scrubbed + "\n").encode("utf-8"))
                        except Exception:
                            pass

                now = time.monotonic()
                if buf and now - last_flush >= _FLUSH_SECS:
                    self._post(self._compress(buf), seq)
                    seq += 1
                    buf = []
                    last_flush = now
                elif not raw:
                    time.sleep(0.5)

            # stop() was called; RPCS3 has exited, file is fully written.
            # Read to EOF to capture the log's final lines.
            while True:
                raw = fh.read(65536)
                if not raw:
                    break
                remainder += raw

            if remainder:
                for line in remainder.split(b"\n"):
                    if not line:
                        continue
                    try:
                        scrubbed = scrubber.scrub(
                            line.decode("utf-8", errors="replace")
                        )
                        buf.append((scrubbed + "\n").encode("utf-8"))
                    except Exception:
                        pass

            payload = self._compress(buf) if buf else zlib.compress(b"")
            self._post(payload, seq, final=True)

        finally:
            fh.close()

    def stop(self):
        self._stop_evt.set()
