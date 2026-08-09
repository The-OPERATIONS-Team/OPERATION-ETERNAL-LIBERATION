"""Unlock logic for OPERATION ETERNAL LIBERATION.

Grants content that was only obtainable during past limited-time events:
event aircraft, and the four cosmetic classes (skins, emblems, nicknames,
radio messages).

Two kinds of operation, dispatched per UnlockSet.op:
  - "aircraft_field": write ownership into the hangar record array (level+avail)
  - "list":           insert ids into a sorted [id BE][00 01] ownership buffer
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from modules import save_editor, unlock_data, tus_saves, games

# Hangar record array layout.
_ARR_STRIDE = 0x34
_REC_TAG_OFFSET = 1
_REC_TAG = 0x14
_OFF_LEVEL = 2
_OFF_AVAIL = 6
_GRANT_LEVEL = 1
_AVAIL_VALUE = 0xD2
_SCAN_START = 0x4000
_SCAN_END = 0x8000

_MARKER_NAME = ".before-unlocks.json"


@dataclass(frozen=True)
class UnlockSet:
    key: str
    label: str
    op: Literal["aircraft_field", "list"]
    ids: tuple[int, ...]
    buf: tuple[int, int] | None = None   # (start_offset, slot_count) for "list"


EVENT_AIRCRAFT = UnlockSet(
    "event_aircraft", "Unlock event aircraft",
    "aircraft_field", tuple(unlock_data.EVENT_AIRCRAFT_IDS))

SKINS = UnlockSet("skins", "Unlock all skins", "list",
                  tuple(unlock_data.SKIN_IDS), unlock_data.SKIN_BUF)
EMBLEMS = UnlockSet("emblems", "Unlock all emblems", "list",
                    tuple(unlock_data.EMBLEM_IDS), unlock_data.EMBLEM_BUF)
NICKNAMES = UnlockSet("nicknames", "Unlock all nicknames", "list",
                      tuple(unlock_data.NICKNAME_IDS), unlock_data.NICKNAME_BUF)
RADIO = UnlockSet("radio", "Unlock all radio messages", "list",
                  tuple(unlock_data.RADIO_IDS), unlock_data.RADIO_BUF)

# The Customization sets, in display order.
CUSTOMIZATION_SETS = (SKINS, EMBLEMS, NICKNAMES, RADIO)
AIRCRAFT_SETS = (EVENT_AIRCRAFT,)


@dataclass
class UnlockResult:
    granted: int
    skipped: int
    missing: int
    total: int

    def add(self, other: "UnlockResult") -> "UnlockResult":
        return UnlockResult(self.granted + other.granted,
                            self.skipped + other.skipped,
                            self.missing + other.missing,
                            self.total + other.total)

    @property
    def changed(self) -> bool:
        return self.granted > 0


def _find_array(data: bytearray) -> tuple[int, int]:
    best = None
    for base in range(_SCAN_START, _SCAN_END):
        if data[base + _REC_TAG_OFFSET] != _REC_TAG:
            continue
        n = 0
        while (base + n * _ARR_STRIDE + _ARR_STRIDE <= len(data)
               and data[base + n * _ARR_STRIDE + _REC_TAG_OFFSET] == _REC_TAG):
            n += 1
        if n >= 200 and (best is None or n > best[1]):
            best = (base, n)
    if best is None:
        raise RuntimeError("hangar array not found in slot 3")
    return best


def _aircraft(data, ids, apply):
    start, count = _find_array(data)
    by_id = {data[start + i * _ARR_STRIDE]: start + i * _ARR_STRIDE
             for i in range(count)}
    g = s = m = 0
    for sid in ids:
        rec = by_id.get(sid)
        if rec is None:
            m += 1
        elif data[rec + _OFF_LEVEL] > 0:
            s += 1
        else:
            g += 1
            if apply:
                data[rec + _OFF_LEVEL] = _GRANT_LEVEL
                data[rec + _OFF_AVAIL] = _AVAIL_VALUE
    return UnlockResult(g, s, m, len(ids))


def _list_read(data, start, slots):
    ids = []
    p = start
    end = start + slots * 4
    while p + 4 <= end:
        idv = (data[p] << 8) | data[p + 1]
        if idv == 0xFFFF:
            break
        ids.append(idv)
        p += 4
    return ids


def _list_write(data, start, slots, ids):
    ids = sorted(set(ids))
    if len(ids) > slots:
        raise ValueError(f"this save already holds {len(ids)} of these, more than "
                         f"the {slots} the game reserves for them")
    p = start
    for v in ids:
        data[p] = (v >> 8) & 0xFF
        data[p + 1] = v & 0xFF
        data[p + 2] = 0x00
        data[p + 3] = 0x01
        p += 4
    end = start + slots * 4
    while p + 4 <= end:
        data[p] = 0xFF
        data[p + 1] = 0xFF
        data[p + 2] = 0x00
        data[p + 3] = 0x00
        p += 4


def _cosmetic(data, ids, buf, apply):
    start, slots = buf
    cur = set(_list_read(data, start, slots))
    added = [x for x in ids if x not in cur]
    if apply and added:
        _list_write(data, start, slots, cur | set(added))
    return UnlockResult(len(added), len(ids) - len(added), 0, len(ids))


def _run(data, unlock_set: UnlockSet, apply: bool) -> UnlockResult:
    if unlock_set.op == "aircraft_field":
        return _aircraft(data, unlock_set.ids, apply)
    return _cosmetic(data, unlock_set.ids, unlock_set.buf, apply)


def preview(slot3: save_editor.SaveSlot, sets) -> UnlockResult:
    if isinstance(sets, UnlockSet):
        sets = (sets,)
    res = UnlockResult(0, 0, 0, 0)
    for s in sets:
        res = res.add(_run(slot3._data, s, apply=False))
    return res


def apply(slot3: save_editor.SaveSlot, sets) -> UnlockResult:
    if isinstance(sets, UnlockSet):
        sets = (sets,)
    res = UnlockResult(0, 0, 0, 0)
    for s in sets:
        res = res.add(_run(slot3._data, s, apply=True))
    return res


def _marker_path(save_dir: str) -> str:
    return os.path.join(save_dir, _MARKER_NAME)


def snapshot_exists(save_dir: str) -> bool:
    return os.path.isfile(_marker_path(save_dir))


def read_marker(save_dir: str) -> dict | None:
    try:
        with open(_marker_path(save_dir), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def ensure_snapshot(save_dir: str, slot3_path: str, applied_label: str):
    """On the first unlock, copy slot 3 into backups/ (launcher format) and
    record a marker. Does nothing if a snapshot already exists."""
    if snapshot_exists(save_dir):
        return
    slot20d = os.path.basename(slot3_path).rsplit("_", 1)[-1].replace(".tdt", "")
    comm_id = games.ACTIVE.comm_id
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backups = os.path.join(save_dir, "backups")
    os.makedirs(backups, exist_ok=True)
    snap = os.path.join(backups, f"{ts}_{comm_id}_{slot20d}.tdt")
    shutil.copy2(slot3_path, snap)
    marker = {
        "snapshot": snap,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "first_unlock": applied_label,
    }
    with open(_marker_path(save_dir), "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2)


def revert(save_dir: str) -> tuple[bool, str]:
    """Stage the pre-unlock snapshot for restore.

    Returns (True, snapshot timestamp) or (False, reason).
    """
    marker = read_marker(save_dir)
    if not marker:
        return False, "No pre-unlock snapshot was found for this save."
    snap = marker.get("snapshot", "")
    if not snap or not os.path.isfile(snap):
        return False, ("The pre-unlock snapshot file is missing. You can still "
                       "restore an earlier save from the Backup / Restore tab.")
    for entry in tus_saves.list_backups(os.path.dirname(save_dir)):
        if os.path.abspath(entry.file_path) == os.path.abspath(snap):
            tus_saves.stage_restore(entry)
            return True, marker.get("created", "")
    # Fall back: stage directly if not found via list_backups.
    slot20d = os.path.basename(snap).rsplit("_", 1)[-1].replace(".tdt", "")
    sentinel = os.path.join(save_dir, f"{slot20d}.tdt.restore")
    shutil.copy2(snap, sentinel)
    return True, marker.get("created", "")
