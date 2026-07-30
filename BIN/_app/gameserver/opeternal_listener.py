"""
OPERATION ETERNAL LIBERATION local mock server.

Two modes:
  - Serve (default): listens on :80 (HTTP) and :443 (HTTPS, self-signed cert
    auto-generated on first run) and answers /Wind/* requests locally.
  - Forward (--forward HOST): runs as a raw TCP relay, forwarding both ports
    to a remote game server. Pass --forward-http-port / --forward-https-port
    if the remote exposes the service on non-default ports.

Adding a new endpoint:
  @route("/Wind/someEndpoint")
  def wind_some_endpoint(body, path, parsed):
      return _response_json({"result": "OK", ...})

Adding a new /Wind/player call:
  Add an entry to _PLAYER_RESPONSES below.
"""

import ctypes
import datetime as _dt
import gzip
import http.server
import json
import os
import socket
import ssl
import sys
import threading
import time
import traceback
import warnings
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit


HERE = Path(__file__).resolve().parent
CERT_PATH = HERE / "cert.pem"
KEY_PATH = HERE / "key.pem"
LOG_DIR = Path(os.environ.get("OEL_LOG_DIR", str(HERE)))

try:
    from community import opeternal_community as _community
except ImportError:
    _community = None

_print_lock = threading.Lock()
_log_file = None


def log(msg):
    line = f"[{_dt.datetime.now().strftime('%H:%M:%S')}] {msg}"
    with _print_lock:
        print(line, flush=True)
        if _log_file and not _log_file.closed:
            _log_file.write(line + "\n")
            _log_file.flush()


# --- File logging ---

def _prune_gz_logs():
    gz_files = sorted(LOG_DIR.glob("gameserver_*.log.gz"), key=lambda p: p.stat().st_mtime)
    for old in gz_files[:-20]:
        try:
            old.unlink()
        except OSError:
            pass


def _rotate_log():
    global _log_file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "gameserver.log"
    if log_path.exists() and log_path.stat().st_size > 0:
        ts = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        gz_path = LOG_DIR / f"gameserver_{ts}.log.gz"
        with log_path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
            dst.write(src.read())
        _prune_gz_logs()
    if log_path.exists():
        log_path.unlink()
    _log_file = log_path.open("a", encoding="utf-8")


def _close_log_on_exit():
    # Leave the log on disk; the next startup rotates it. The launcher's
    # log watcher reads it between sessions.
    global _log_file
    if _log_file and not _log_file.closed:
        try:
            _log_file.flush()
        except OSError:
            pass
        _log_file.close()
        _log_file = None


_ctrl_handler_ref = None  # must stay alive for the lifetime of the process


def _install_close_handler():
    global _ctrl_handler_ref
    if sys.platform != "win32":
        return
    import ctypes.wintypes
    HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.DWORD)

    def _handler(event):
        # 2=CTRL_CLOSE_EVENT  5=CTRL_LOGOFF_EVENT  6=CTRL_SHUTDOWN_EVENT
        if event in (2, 5, 6):
            log("shutting down")
            _close_log_on_exit()
        return False

    _ctrl_handler_ref = HandlerRoutine(_handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_ctrl_handler_ref, True)


# --- TLS cert ---

def ensure_cert():
    if CERT_PATH.exists() and KEY_PATH.exists():
        return
    print("[setup] generating self-signed TLS cert ...")
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        helper = "setup.bat" if sys.platform == "win32" else "setup.sh"
        sys.exit(
            "[setup] missing 'cryptography' package.\n"
            f"        run {helper} then re-run this script."
        )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "dev-wind.siliconstudio.co.jp"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OP ETERNAL Mock"),
    ])
    san = x509.SubjectAlternativeName([
        x509.DNSName("dev-wind.siliconstudio.co.jp"),
        x509.DNSName("a0.ww.np.dl.playstation.net"),
        x509.DNSName("localhost"),
    ])
    now = _dt.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(days=1))
        .not_valid_after(now + _dt.timedelta(days=365 * 10))
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    CERT_PATH.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    KEY_PATH.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    print(f"[setup] wrote {CERT_PATH.name} / {KEY_PATH.name}")


def _looks_like_tls_client_hello(sock):
    try:
        first = sock.recv(1, socket.MSG_PEEK)
    except (BlockingIOError, InterruptedError):
        return True
    except socket.timeout:
        raise
    except OSError:
        return False
    return bool(first and first[0] == 0x16)


# --- Routing ---
# Handlers are registered via @route and receive (body, path, parsed).
# Longest prefix wins. Unmatched requests return {"result": "OK"}.

_routes: list[tuple[str, callable]] = []


def route(prefix: str):
    """Register a handler for any request path that starts with prefix."""
    def decorator(fn):
        _routes.append((prefix, fn))
        _routes.sort(key=lambda r: len(r[0]), reverse=True)
        return fn
    return decorator


def _find_handler(path: str):
    for prefix, handler in _routes:
        if path.startswith(prefix):
            return handler
    return None


# --- Response helpers ---

def _response_json(obj, status=200):
    return status, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8")

_OK = _response_json({"result": "OK"})


# --- Endpoints ---

@route("/Wind/authorize")
def wind_authorize(body, path, parsed):
    return _response_json({"result": "OK"})


# /Wind/player dispatches on the "call" field in the request body.
# Add new call types here as they are discovered.
_PLAYER_RESPONSES = {
    "getRecoveryInfo": {
        "result": "OK",
        "data": {"recovery_id": 0},
    },
    "getNews": {
        "result": "OK",
        "data": {"newsList": []},
    },
    "getRankingRegulation": {
        "result": "OK",
        "data": {
            "regurations": [{
                "ev_id": 1,
                "ev_name": "TestRegulation",
                "long_event_name": "TestRegulationLong",
                "present_name_str": "PresentName",
                "ranking_type_name": "RankingTypeName",
                "mission_name": "MissionName",
                "max_winner_rank": 1,
                "info_begin_time": "",
                "begin_time": "",
                "interim_time": "",
                "end_time": "",
                "result_disp_time": "",
                "receive_reward_time": 1,
                "status": 0,
                "matching_regulation_id": 1,
                "ranking_rule_id": 1,
                "target_missions": [101, 102, 103, 104, 105, 106, 107, 108],
                "target_aircrafts": [
                    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
                    21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 38, 58,
                    59, 60, 61, 74, 75, 83, 84, 85, 97, 110, 114, 115, 116, 117, 139, 140,
                    141, 142, 154, 155, 156, 157, 158, 192, 193, 194, 208, 211, 212, 213,
                ],
                "use_original_aircraft_id": 1,
                "present_items": [{"rank": 1}],
                "url_option": "",
            }],
        },
    },
}

@route("/Wind/player")
def wind_player(body, path, parsed):
    call = (parsed or {}).get("call", "")
    return _response_json(_PLAYER_RESPONSES.get(call, {"result": "OK", "data": {}}))


# --- Request body parsing ---

def _parse_body(headers, body):
    if not body:
        return None
    decoded = body
    if (headers.get("Content-Encoding") or "").lower() == "gzip":
        try:
            decoded = gzip.decompress(body)
        except Exception:
            pass
    if decoded.lstrip()[:1] in (b"{", b"["):
        try:
            return json.loads(decoded)
        except Exception:
            pass
    return None


# --- HTTP server ---

# Bound the TLS sniff/handshake and per-request reads. A stalled or half-open
# client (typically a port scanner) must never wedge the single accept thread
# or tie up a worker thread forever.
HANDSHAKE_TIMEOUT = 10
REQUEST_TIMEOUT = 30


class ACIHandler(http.server.BaseHTTPRequestHandler):
    server_version = "ACIMock/2.0"
    timeout = REQUEST_TIMEOUT

    def log_message(self, fmt, *args):
        return

    def _read_body(self):
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            chunks = []
            while True:
                size_line = self.rfile.readline(65536)
                if not size_line:
                    break
                try:
                    size = int(size_line.split(b";", 1)[0].strip(), 16)
                except ValueError:
                    break
                if size == 0:
                    while self.rfile.readline(65536) not in (b"\r\n", b"\n", b""):
                        pass
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.read(2)
            return b"".join(chunks)
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length > 0 else b""

    def _serve(self, method):
        body = self._read_body()
        path = urlsplit(self.path).path
        parsed = _parse_body(self.headers, body)

        req_info = f">>> {method} {self.headers.get('Host', '')}{self.path}"
        if parsed:
            req_info += f"  {json.dumps(parsed, ensure_ascii=False)}"
        log(req_info)

        status, ctype, payload = _OK
        try:
            handler = _find_handler(path)
            if handler:
                status, ctype, payload = handler(body, path, parsed)
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
        except Exception:
            log(f"[error] handler failed:\n{traceback.format_exc()}")
            status, ctype, payload = _response_json({"result": 1, "error": "internal server error"}, status=500)

        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload or b"")))
        self.send_header("Connection", "close")
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(payload or b"")
        log(f"<<< {status}  {(payload or b'').decode('utf-8', errors='replace')}")

    def do_GET(self):     self._serve("GET")
    def do_POST(self):    self._serve("POST")
    def do_PUT(self):     self._serve("PUT")
    def do_DELETE(self):  self._serve("DELETE")
    def do_HEAD(self):    self._serve("HEAD")
    def do_PATCH(self):   self._serve("PATCH")
    def do_OPTIONS(self): self._serve("OPTIONS")


class ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def handle_error(self, request, client_address):
        log(f"[server] error for {client_address}:\n{traceback.format_exc()}")


class Port443Server(ThreadingHTTPServer):
    """Port 443 accepts TLS or plaintext HTTP."""

    def __init__(self, addr, handler, ctx):
        super().__init__(addr, handler)
        self._ctx = ctx

    def get_request(self):
        sock, addr = self.socket.accept()
        # A stalled or half-open client must never wedge this single accept
        # thread, so bound the TLS sniff and handshake with a timeout. A timeout
        # raises OSError, which socketserver treats as a dropped connection and
        # keeps accepting. The worker gets a blocking socket back (the handler
        # re-applies its own REQUEST_TIMEOUT).
        sock.settimeout(HANDSHAKE_TIMEOUT)
        try:
            is_tls = _looks_like_tls_client_hello(sock)
        except OSError:
            sock.close()
            raise
        if not is_tls:
            sock.settimeout(None)
            return sock, addr
        try:
            tls = self._ctx.wrap_socket(sock, server_side=True)
        except Exception as exc:
            log(f"[tls] handshake FAILED from {addr[0]}:{addr[1]}: {exc}")
            try:
                sock.close()
            except Exception:
                pass
            raise
        tls.settimeout(None)
        return tls, addr


def _make_ssl_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_PATH, KEY_PATH)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        ctx.minimum_version = ssl.TLSVersion.TLSv1
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0:!aNULL:!eNULL")
    except ssl.SSLError:
        pass
    return ctx


def serve_http(host, port):
    httpd = ThreadingHTTPServer((host, port), ACIHandler)
    log(f"[http] listening on {host}:{port}")
    httpd.serve_forever()


def serve_https(host, port):
    ctx = _make_ssl_context()
    httpd = Port443Server((host, port), ACIHandler, ctx)
    log(f"[https] listening on {host}:{port} (cert={CERT_PATH.name})")
    httpd.serve_forever()


# --- Raw TCP forwarder ---

def _pipe(src_sock, dst_sock):
    try:
        while True:
            data = src_sock.recv(65536)
            if not data:
                break
            dst_sock.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst_sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _handle_forward(client_sock, client_addr, remote_host, remote_port):
    try:
        upstream = socket.create_connection((remote_host, remote_port), timeout=10)
    except OSError as e:
        log(f"[forward] {client_addr[0]}:{client_addr[1]} -> {remote_host}:{remote_port} FAILED: {e}")
        try:
            client_sock.close()
        except OSError:
            pass
        return
    log(f"[forward] {client_addr[0]}:{client_addr[1]} -> {remote_host}:{remote_port}")
    t = threading.Thread(target=_pipe, args=(upstream, client_sock), daemon=True)
    t.start()
    _pipe(client_sock, upstream)
    try:
        client_sock.close()
    except OSError:
        pass
    try:
        upstream.close()
    except OSError:
        pass


def serve_forward(bind_host, bind_port, remote_host, remote_port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((bind_host, bind_port))
    except OSError as e:
        log(f"[forward] cannot bind {bind_host}:{bind_port}: {e}")
        return
    srv.listen(64)
    log(f"[forward] {bind_host}:{bind_port} -> {remote_host}:{remote_port}")
    while True:
        try:
            client, addr = srv.accept()
        except OSError:
            break
        threading.Thread(
            target=_handle_forward,
            args=(client, addr, remote_host, remote_port),
            daemon=True,
        ).start()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="OPERATION ETERNAL LIBERATION local mock server")
    parser.add_argument("--bind-ip", default=os.environ.get("ACI_BIND_IP", "0.0.0.0"))
    parser.add_argument("--http-port", type=int, default=int(os.environ.get("ACI_HTTP_PORT", "80")))
    parser.add_argument("--https-port", type=int, default=int(os.environ.get("ACI_HTTPS_PORT", "443")))
    parser.add_argument("--no-https", action="store_true")
    parser.add_argument(
        "--forward",
        default=None,
        help="Forward all traffic to this remote game server (raw TCP relay) instead of serving locally.",
    )
    parser.add_argument("--forward-http-port", type=int, default=80,
                        help="Remote port to forward HTTP (:80) traffic to. Default 80.")
    parser.add_argument("--forward-https-port", type=int, default=443,
                        help="Remote port to forward HTTPS (:443) traffic to. Default 443.")
    parser.add_argument(
        "--watch-pid",
        type=int,
        default=None,
        help="Exit when this process ID is no longer running.",
    )
    args = parser.parse_args()

    _rotate_log()
    _install_close_handler()

    if _community and _community.enabled():
        _community.install(route)
        _community.init()

    art_file = HERE.parent / "assets" / "ascii.txt"
    if art_file.exists():
        print(art_file.read_text(encoding="utf-8", errors="replace").rstrip(), flush=True)
        print(flush=True)

    log("=" * 60)
    if args.forward:
        log(f"OP ETERNAL forwarder starting (remote: {args.forward})")
    else:
        log("OP ETERNAL mock server starting")
    log("=" * 60)

    if args.forward:
        threads = [threading.Thread(
            target=serve_forward,
            args=(args.bind_ip, args.http_port, args.forward, args.forward_http_port),
            daemon=True,
        )]
        if not args.no_https:
            threads.append(threading.Thread(
                target=serve_forward,
                args=(args.bind_ip, args.https_port, args.forward, args.forward_https_port),
                daemon=True,
            ))
    else:
        ensure_cert()
        threads = [threading.Thread(target=serve_http, args=(args.bind_ip, args.http_port), daemon=True)]
        if not args.no_https:
            threads.append(threading.Thread(target=serve_https, args=(args.bind_ip, args.https_port), daemon=True))

    for t in threads:
        t.start()

    try:
        while True:
            if args.watch_pid is not None:
                try:
                    os.kill(args.watch_pid, 0)
                except ProcessLookupError:
                    log(f"watched process {args.watch_pid} exited; shutting down")
                    break
                except PermissionError:
                    pass
            time.sleep(1)
    except KeyboardInterrupt:
        log("shutting down")
    finally:
        _close_log_on_exit()


if __name__ == "__main__":
    main()
