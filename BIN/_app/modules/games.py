"""Game profiles: the region-specific identifiers (title ID, comm ID) the
launcher builds its paths, config, RPCN and saves from.

Add a GameProfile to support a region, and a data/game_manifest.json entry for a
supported one. A supported=False profile is detected when installed but never
becomes ACTIVE.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GameProfile:
    title_id: str          # PS3 product code, the dev_hdd0/game/<id> folder
    comm_id: str           # PSN communication ID (TSS / TUS saves / trophies)
    region: str            # "US" / "EU" / "JP"
    name: str
    supported: bool = True

    @property
    def config_name(self) -> str:
        """RPCS3 per-game custom config file name."""
        return f"config_{self.title_id}.yml"


# Blank comm_id on the unsupported titles; only supported ones use it.
PROFILES: dict[str, GameProfile] = {
    "NPUB31347": GameProfile("NPUB31347", "NPWR04428_00", "US", "Ace Combat Infinity (US)", True),
    "NPEB01839": GameProfile("NPEB01839", "", "EU", "Ace Combat Infinity (EU)", False),
    "NPJB00481": GameProfile("NPJB00481", "", "JP", "Ace Combat Infinity (JP)", False),
}

# The title the launcher runs; everything but verification uses it.
ACTIVE: GameProfile = PROFILES["NPUB31347"]


@dataclass(frozen=True)
class InstalledGame:
    profile: GameProfile
    game_dir: Path        # directory holding PARAM.SFO and USRDIR

    @property
    def param_sfo(self) -> Path:
        return self.game_dir / "PARAM.SFO"


def _read_games_yml(path) -> dict:
    """Serial -> directory map from an RPCS3 games.yml. Parsed leniently
    ('SERIAL: path' per line, value optionally quoted) to avoid a YAML dep;
    the drive-letter colon stays with the value since we split on the first."""
    out: dict[str, str] = {}
    try:
        text = Path(path).read_text("utf-8", "replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition(":")
        if not sep:
            continue
        val = val.strip().strip('"').strip("'")
        if key.strip() and val:
            out[key.strip()] = val
    return out


def find_installed(game_base, games_yml=None) -> InstalledGame | None:
    """Locate an installed title, supported or not, else None. Prefers the
    emulator's virtual HDD (where Install Packages lands), then falls back to a
    folder the user added through RPCS3 (recorded in games.yml)."""
    base = Path(game_base)
    for profile in PROFILES.values():
        game_dir = base / profile.title_id
        if (game_dir / "PARAM.SFO").is_file():
            return InstalledGame(profile, game_dir)
    if games_yml is not None:
        registered = _read_games_yml(games_yml)
        for profile in PROFILES.values():
            val = registered.get(profile.title_id)
            if val and (Path(val) / "PARAM.SFO").is_file():
                return InstalledGame(profile, Path(val))
    return None
