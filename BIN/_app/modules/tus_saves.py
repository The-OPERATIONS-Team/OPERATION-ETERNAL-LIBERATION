"""TUS save backup and restore, ported from clear/restore_tus_save.ps1.

Backup files live at:
    <tus_root>/<comm_id>/<npid>/backups/YYYY-MM-DD_HHMMSS_<comm_id>_<slot20d>.tdt

Restore sentinels are written to:
    <tus_root>/<comm_id>/<npid>/<slot20d>.tdt.restore
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import games


@dataclass
class BackupEntry:
    date: str       # "YYYY-MM-DD"
    time: str       # "HH:MM:SS"
    session: str    # "YYYY-MM-DD_HHMM"  (groups same-minute saves)
    slot: str       # 20-digit zero-padded slot ID
    size_kb: int
    file_path: str
    slot_dir: str   # directory that receives the .tdt.restore sentinel


def list_backups(tus_root: str) -> list[BackupEntry]:
    """Scan tus_root for all timestamped backup .tdt files."""
    entries: list[BackupEntry] = []
    root = Path(tus_root)
    if not root.exists():
        return entries

    for f in sorted(root.rglob("*.tdt")):
        if f.parent.name != "backups":
            continue
        n = f.stem  # e.g. 2026-05-10_182917_<comm_id>_00000000000000000002
        parts = n.split("_")
        # Minimum: date(1) + time(1) + comm_id parts + slot(1)
        if len(parts) < 4:
            continue
        slot = parts[-1]
        if not re.fullmatch(r"\d{20}", slot):
            continue

        date    = parts[0]           # YYYY-MM-DD
        raw_t   = parts[1]           # HHMMSS
        time_s  = f"{raw_t[0:2]}:{raw_t[2:4]}:{raw_t[4:6]}" if len(raw_t) >= 6 else raw_t
        session = f"{date}_{raw_t[0:4]}"

        entries.append(BackupEntry(
            date=date,
            time=time_s,
            session=session,
            slot=slot,
            size_kb=max(1, (f.stat().st_size + 1023) // 1024),
            file_path=str(f),
            slot_dir=str(f.parent.parent),  # strip /backups
        ))

    return entries


def stage_restore(entry: BackupEntry) -> str | None:
    """Copy backup .tdt to its .tdt.restore sentinel.

    Returns None on success or an error string on failure.
    """
    sentinel = os.path.join(entry.slot_dir, f"{entry.slot}.tdt.restore")
    try:
        import shutil
        shutil.copy2(entry.file_path, sentinel)
        return None
    except OSError as e:
        return str(e)


COMM_ID = games.ACTIVE.comm_id

DEFAULT_NEW_GAME_SLOTS = (
    "00000000000000000002",
    "00000000000000000003",
    "00000000000000000004",
    "00000000000000000008",
)


def _read_npid_from_rpcn_yml(rpcn_yml_path: str) -> str | None:
    try:
        with open(rpcn_yml_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("NPID:"):
                    return line.split(":", 1)[1].strip().strip('"').strip() or None
    except OSError:
        return None
    return None


def stage_new_game(tus_root: str, rpcn_yml_path: str) -> tuple[int, list[str]]:
    """Stage .tdt.restore files so the game offers a fresh start on next boot."""
    npid = _read_npid_from_rpcn_yml(rpcn_yml_path)
    if not npid:
        return 0, [
            "No RPCN username in rpcn.yml. "
            "Launch RPCS3 once and sign into RPCN, then try again."
        ]

    slot_dir = Path(tus_root) / COMM_ID / npid
    try:
        slot_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return 0, [f"Could not create {slot_dir}: {e}"]

    found: set[str] = set()
    backups = slot_dir / "backups"
    if backups.is_dir():
        for f in backups.glob("*.tdt"):
            parts = f.stem.split("_")
            if parts and re.fullmatch(r"\d{20}", parts[-1]):
                found.add(parts[-1])
    for f in slot_dir.glob("*.tdt"):
        if re.fullmatch(r"\d{20}", f.stem):
            found.add(f.stem)
    for f in slot_dir.glob("*.tdt.restore"):
        slot = f.name[: -len(".tdt.restore")]
        if re.fullmatch(r"\d{20}", slot):
            found.add(slot)

    slots_to_stage = found if found else set(DEFAULT_NEW_GAME_SLOTS)

    staged = 0
    errors: list[str] = []
    for slot in slots_to_stage:
        target = slot_dir / f"{slot}.tdt.restore"
        try:
            target.write_bytes(b"")
            staged += 1
        except OSError as e:
            errors.append(f"Could not write {target}: {e}")

    return staged, errors


def cleanup_restore_sentinels(tus_root: str) -> int:
    """Delete all dangling .tdt.restore sentinels under tus_root.

    Returns the number of files removed.
    """
    root = Path(tus_root)
    if not root.exists():
        return 0
    count = 0
    for f in root.rglob("*.tdt.restore"):
        try:
            f.unlink()
            count += 1
        except OSError:
            pass
    return count
