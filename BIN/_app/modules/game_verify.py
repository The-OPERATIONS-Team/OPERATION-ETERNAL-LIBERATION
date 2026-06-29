"""Game installation verification for OP ETERNAL.

Parses PARAM.SFO for the installed game version, hashes the game's .PAC,
.edat and .BIN files, and compares those plus the approximate install size
against a known-good manifest (data/game_manifest.json).
"""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .hash_util import hash_file

EXPECTED_VERSION = "2.11"
VERIFY_SUFFIXES = (".pac", ".edat", ".bin")
SIZE_TOLERANCE = 0.02  # +/-2% on the approximate install size

_SFO_MAGIC = b"\x00PSF"
_FMT_UINT32 = 0x0404


def parse_sfo(path: Path) -> dict:
    """Return the key/value index of a PS3 PARAM.SFO. String values come back
    as str, integer values as int. Raises ValueError on a malformed file."""
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != _SFO_MAGIC:
        raise ValueError("not a PARAM.SFO")
    try:
        _, key_start, data_start, count = struct.unpack_from("<IIII", data, 4)
        out: dict[str, object] = {}
        for i in range(count):
            key_off, fmt, dlen, _dmax, data_off = struct.unpack_from("<HHIII", data, 20 + i * 16)
            key_end = data.index(b"\x00", key_start + key_off)
            key = data[key_start + key_off:key_end].decode("utf-8", "replace")
            raw = data[data_start + data_off:data_start + data_off + dlen]
            if fmt == _FMT_UINT32:
                out[key] = struct.unpack_from("<I", raw)[0]
            else:
                out[key] = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
        return out
    except struct.error as e:
        raise ValueError(str(e)) from e


def normalize_version(v: str) -> str:
    """'02.11' -> '2.11'. Leaves anything unrecognised untouched."""
    v = (v or "").strip()
    head, dot, tail = v.partition(".")
    if dot and head.isdigit():
        return f"{int(head)}.{tail}"
    return v


def read_game_version(param_sfo: Path) -> dict:
    """{'APP_VER': .., 'VERSION': ..} as found in PARAM.SFO, best-effort."""
    try:
        sfo = parse_sfo(param_sfo)
    except (OSError, ValueError):
        return {}
    return {k: str(sfo[k]) for k in ("APP_VER", "VERSION") if k in sfo}


def iter_game_files(game_dir: Path):
    """Yield (relative_posix_path, absolute_path) for every verifiable file."""
    for p in sorted(game_dir.rglob("*"), key=lambda q: q.as_posix().lower()):
        if p.is_file() and p.suffix.lower() in VERIFY_SUFFIXES:
            yield p.relative_to(game_dir).as_posix(), p


def dir_size(root: Path) -> int:
    total = 0
    for p in root.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def load_manifest(path: Path) -> dict:
    try:
        m = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}


FileStatus = Literal["ok", "mismatch", "missing", "unexpected", "unconfigured", "error"]


@dataclass
class FileResult:
    rel: str
    size: int
    sha256: str
    status: FileStatus


@dataclass
class VerifyResult:
    title_id: str
    region: str
    version_found: dict
    version_expected: str
    version_ok: bool
    size_bytes: int
    size_expected: int | None
    size_ok: bool | None            # None = not configured in the manifest
    files: list
    hashes_configured: bool

    @property
    def ok(self) -> bool:
        if not self.version_ok:
            return False
        if self.size_ok is False:
            return False
        return not any(f.status in ("mismatch", "missing", "error") for f in self.files)


def game_entry(manifest: dict, title_id: str) -> dict:
    """The per-title entry for title_id from a manifest, or {} if absent."""
    games = manifest.get("games")
    if isinstance(games, dict) and isinstance(games.get(title_id), dict):
        return games[title_id]
    return {}


def verify(game_dir: Path, param_sfo: Path, entry: dict, progress=None) -> VerifyResult:
    """Hash the game files and compare them, the version and the size against a
    single-title manifest entry. ``progress(done, total, rel)`` is called per
    file if given."""
    title_id = Path(game_dir).name
    region = str(entry.get("region") or "")
    expected_version = normalize_version(entry.get("game_version") or EXPECTED_VERSION)
    expected_files = dict(entry.get("files") or {})
    expected_size = entry.get("approx_size_bytes")
    hashes_configured = bool(expected_files)

    found = read_game_version(param_sfo)
    version_ok = expected_version in {normalize_version(v) for v in found.values()}

    results: list[FileResult] = []
    seen: set[str] = set()
    files = list(iter_game_files(game_dir))
    for i, (rel, ap) in enumerate(files):
        if progress:
            progress(i, len(files), rel)
        try:
            digest = hash_file(ap)
            size = ap.stat().st_size
            status = "ok"
        except OSError:
            digest, size, status = "", 0, "error"
        seen.add(rel)
        if status != "error":
            if not hashes_configured:
                status = "unconfigured"
            elif rel not in expected_files:
                status = "unexpected"
            elif expected_files[rel].lower() == digest.lower():
                status = "ok"
            else:
                status = "mismatch"
        results.append(FileResult(rel, size, digest, status))

    if hashes_configured:
        for rel in expected_files:
            if rel not in seen:
                results.append(FileResult(rel, 0, "", "missing"))

    size_bytes = dir_size(game_dir)
    if expected_size:
        size_ok = expected_size * (1 - SIZE_TOLERANCE) <= size_bytes <= expected_size * (1 + SIZE_TOLERANCE)
    else:
        size_ok = None

    return VerifyResult(title_id, region, found, expected_version, version_ok,
                        size_bytes, expected_size, size_ok, results, hashes_configured)


def fingerprint(result: VerifyResult) -> str:
    """Stable per-install digest for telemetry: SHA-256 over the sorted
    'rel:sha256' lines of the verifiable game files."""
    h = hashlib.sha256()
    for fr in sorted(result.files, key=lambda f: f.rel.lower()):
        if fr.sha256:
            h.update(f"{fr.rel}:{fr.sha256}\n".encode("utf-8"))
    return h.hexdigest()


def install_signature(game_dir: Path, param_sfo: Path) -> str:
    """SHA-256 over the (path, size, mtime) of PARAM.SFO and every verifiable
    file. Lets the launcher re-verify a changed install without re-hashing on
    every poll."""
    h = hashlib.sha256()
    targets = [("PARAM.SFO", Path(param_sfo))]
    targets += list(iter_game_files(Path(game_dir)))
    for rel, p in targets:
        try:
            st = p.stat()
            h.update(f"{rel}:{st.st_size}:{st.st_mtime_ns}\n".encode("utf-8"))
        except OSError:
            h.update(f"{rel}:missing\n".encode("utf-8"))
    return h.hexdigest()
