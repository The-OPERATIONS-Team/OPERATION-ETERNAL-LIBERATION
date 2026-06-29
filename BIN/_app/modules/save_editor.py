"""OP ETERNAL save file editor, core logic extracted from aci_save_editor.py.

Provides SaveSlot for reading and writing .tdt save files used by
OPERATION ETERNAL LIBERATION.  CRC algorithm: CRC-32/BZIP2.
"""
import struct

# ---------------------------------------------------------------------------
# CRC-32/BZIP2  (poly 0x04C11DB7, init 0xFFFFFFFF, MSB-first, xorout 0xFFFFFFFF)
# ---------------------------------------------------------------------------

def crc32_bzip2(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc ^ 0xFFFFFFFF

assert crc32_bzip2(b"123456789") == 0xFC891918, "CRC self-test failed"

MAGIC = b"SAVE"

# ---------------------------------------------------------------------------
# Slot metadata and field table (identical to aci_save_editor.py)
# Use tools\save_files_analyzer.py to find the correct slots and offsets to put into the FIELDS array.
# ---------------------------------------------------------------------------

SLOTS = {
    2: dict(file_size=0x0440,  entry_count=1,  data_zone=0x0024),
    3: dict(file_size=0x16DE8, entry_count=17, data_zone=0x00E4),
    4: dict(file_size=0x0078,  entry_count=3,  data_zone=0x003C),
}

# The maximum value is set to 999999000 (and not 999999999) because if, either due to a game bonus event or any other
# cause, the current value would go above 999999999, then either the game's save validation system will not allow the
# save data to be loaded until next game restart.
# As a result we keep the maximum value lower to reduce the possibility of this happening.
FIELDS = [
    dict(slot=3, arg="credits",           label="Credits",
         offset=0x4848, fmt="u32", max=999999000, copies=[0x484C, 0x4854]),

    dict(slot=2, arg="fuel",               label="Stocked Fuel",
         offset=0x0074, fmt="u32", max=999999000),
    dict(slot=2, arg="aircraft-research", label="Aircraft Research Reports",
         offset=0x00EC, fmt="u32", max=999999000),
    dict(slot=2, arg="sw-research", label="Special Weapons Research Reports",
         offset=0x0104, fmt="u32", max=999999000),
    dict(slot=2, arg="parts-research",   label="Parts Research Reports",
         offset=0x011C, fmt="u32", max=999999000),
    dict(slot=2, arg="tickets",            label="Special Supply Tickets",
         offset=0x0164, fmt="u32", max=999999000),
    dict(slot=2, arg="ns-upgrade-forms",  label="Nonstandard Upgrade Forms",
         offset=0x008C, fmt="u32", max=999999000),
    dict(slot=2, arg="lv-cap-forms",      label="Lv. Cap Increase Forms",
         offset=0x00BC, fmt="u32", max=999999000),
    dict(slot=2, arg="pilot-medals",      label="Skilled Pilot Medals",
         offset=0x0254, fmt="u32", max=999999000),

    dict(slot=4, arg="penalty-rank",      label="Penalty Rank",
         offset=0x0040, fmt="u32", max=999999000),
]

FIELDS_BY_SLOT = {s: [f for f in FIELDS if f["slot"] == s] for s in (2, 3, 4)}

# Online Co-Op Missions Matching Rate. Slot 3, 0xBC70, big-endian u16.
COOP_MATCH_RATE_SLOT   = 3
COOP_MATCH_RATE_OFFSET = 0xBC70
COOP_MATCH_RATE_FLOOR  = 1550

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _read_u32(data: bytearray, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]

def _write_u32(data: bytearray, offset: int, value: int):
    struct.pack_into(">I", data, offset, value)

def _read_u16(data: bytearray, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]

def _write_u16(data: bytearray, offset: int, value: int):
    struct.pack_into(">H", data, offset, value)

def _recompute_crcs(data: bytearray, entry_count: int, data_zone: int):
    TABLE_START = 0x18
    ENTRY_SIZE  = 12
    for i in range(entry_count):
        entry_off = TABLE_START + i * ENTRY_SIZE
        length    = _read_u32(data, entry_off)
        offset    = _read_u32(data, entry_off + 4)
        _write_u32(data, entry_off + 8, crc32_bzip2(bytes(data[offset:offset + length])))
    _write_u32(data, 0x08, crc32_bzip2(bytes(data[data_zone:len(data)])))

def _verify_crcs(data: bytearray, entry_count: int, data_zone: int) -> bool:
    TABLE_START = 0x18
    ENTRY_SIZE  = 12
    for i in range(entry_count):
        entry_off = TABLE_START + i * ENTRY_SIZE
        length    = _read_u32(data, entry_off)
        offset    = _read_u32(data, entry_off + 4)
        stored    = _read_u32(data, entry_off + 8)
        if crc32_bzip2(bytes(data[offset:offset + length])) != stored:
            return False
    return crc32_bzip2(bytes(data[data_zone:len(data)])) == _read_u32(data, 0x08)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class SaveSlot:
    """Wraps a loaded .tdt save file for a specific slot number (2 or 3)."""

    def __init__(self, slot_num: int, path: str):
        if slot_num not in SLOTS:
            raise ValueError(f"Unknown slot number {slot_num}")
        meta = SLOTS[slot_num]
        with open(path, "rb") as f:
            self._data = bytearray(f.read())
        if len(self._data) != meta["file_size"]:
            raise ValueError(
                f"Slot {slot_num}: expected {meta['file_size']} bytes, got {len(self._data)}"
            )
        if self._data[:4] != MAGIC:
            raise ValueError("Not a valid OP ETERNAL save file (missing SAVE magic)")
        self.slot_num = slot_num
        self._path    = path
        self._meta    = meta

    def read_all(self) -> dict[str, int]:
        """Return {arg_name: value} for all known fields in this slot."""
        return {
            f["arg"]: self._get(f)
            for f in FIELDS_BY_SLOT[self.slot_num]
        }

    def write_field(self, arg: str, value: int):
        """Set a field by its arg name. Raises ValueError on bad value."""
        for f in FIELDS_BY_SLOT[self.slot_num]:
            if f["arg"] == arg:
                if not (0 <= value <= f["max"]):
                    raise ValueError(f"{f['label']} must be 0..{f['max']:,}, got {value:,}")
                for off in [f["offset"]] + f.get("copies", []):
                    if f["fmt"] == "u32":
                        _write_u32(self._data, off, value)
                    else:
                        self._data[off] = value
                return
        raise KeyError(f"Unknown field arg '{arg}' for slot {self.slot_num}")

    def read_coop_match_rate(self) -> int:
        """Read the Online Co-Op Missions Matching Rate (slot 3 only)."""
        if self.slot_num != COOP_MATCH_RATE_SLOT:
            raise ValueError("Co-Op Matching Rate lives in slot 3")
        return _read_u16(self._data, COOP_MATCH_RATE_OFFSET)

    def write_coop_match_rate(self, value: int):
        """Set the Online Co-Op Missions Matching Rate (slot 3 only)."""
        if self.slot_num != COOP_MATCH_RATE_SLOT:
            raise ValueError("Co-Op Matching Rate lives in slot 3")
        if not (0 <= value <= 0xFFFF):
            raise ValueError(f"Co-Op Matching Rate must be 0..65535, got {value}")
        _write_u16(self._data, COOP_MATCH_RATE_OFFSET, value)

    def verify(self) -> bool:
        return _verify_crcs(self._data, self._meta["entry_count"], self._meta["data_zone"])

    def save(self, path: str | None = None):
        """Recompute all CRCs and write to path (defaults to original path)."""
        _recompute_crcs(self._data, self._meta["entry_count"], self._meta["data_zone"])
        if not self.verify():
            raise RuntimeError("CRC verification failed after recompute; file not saved")
        out = path or self._path
        with open(out, "wb") as f:
            f.write(self._data)

    def _get(self, f: dict) -> int:
        if f["fmt"] == "u32":
            return _read_u32(self._data, f["offset"])
        return self._data[f["offset"]]


def fields_for_slot(slot_num: int) -> list[dict]:
    """Return the FIELDS entries for the given slot number."""
    return FIELDS_BY_SLOT.get(slot_num, [])
