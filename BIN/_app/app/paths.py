"""Filesystem paths, app constants, and platform resolvers.

Everything is derived from the location of the _app/ directory so the launcher
works from wherever the user unpacked it.
"""
import os
import shutil
import sys
from pathlib import Path

_IS_WIN     = sys.platform == "win32"
_EXE        = ".exe" if _IS_WIN else ""

APP_DIR     = Path(__file__).resolve().parent.parent   # _app/
ROOT_DIR    = APP_DIR.parent                            # folder user sees (where TSS/ lives)
RPCS3_DIR   = APP_DIR / "RPCS3"
RPCN_DIR    = APP_DIR / "rpcn"
GAMESERVER_DIR = APP_DIR / "gameserver"
PATCHES_DIR = APP_DIR / "patches"

# Game-profile registry (used by the path constants).
sys.path.insert(0, str(APP_DIR))
from modules import games
PYTHON_EXE  = APP_DIR / "python" / "python.exe" if _IS_WIN else APP_DIR / "python" / "bin" / "python3"


def _resolve_rpcs3_exe() -> Path:
    if _IS_WIN:
        return RPCS3_DIR / "rpcs3.exe"
    images = sorted(RPCS3_DIR.glob("*.AppImage"))
    if images:
        return images[0]
    return RPCS3_DIR / "rpcs3"


RPCS3_EXE   = _resolve_rpcs3_exe()
RPCN_EXE    = RPCN_DIR / f"rpcn{_EXE}"
GAMESERVER_SCRIPT = GAMESERVER_DIR / "opeternal_listener.py"
GAMESERVER_LOG    = GAMESERVER_DIR / "gameserver.log"
PORTABLE_DIR = RPCS3_DIR / "portable"
# RPCS3 keeps yml configs in a config/ subdirectory only on Windows; elsewhere
# they sit directly in the portable dir (fs::get_config_dir).
RPCS3_CFG_DIR = PORTABLE_DIR / "config" if _IS_WIN else PORTABLE_DIR
RPCN_YML    = RPCS3_CFG_DIR / "rpcn.yml"
CUSTOM_CFG  = RPCS3_CFG_DIR / "custom_configs" / games.ACTIVE.config_name
TSS_SRC_DIR = ROOT_DIR / "TSS"
RPCS3_TSS   = PORTABLE_DIR / "tss"
RPCN_TSS    = RPCN_DIR / "tss_data" / games.ACTIVE.comm_id
SETTINGS_FILE = APP_DIR / "settings.json"

VERSION          = "1.0.2.4"
RELEASE_CHANNEL  = "experimental"   # "main" for stable releases, "experimental" for pre-releases
GITHUB_REPO      = "The-OPERATIONS-Team/OPERATION-ETERNAL-LIBERATION"

COMMUNITY_RPCN_HOST  = "np.rpcs3.net"
OPERATIONS_GAME_ADDR = "oel-game.killerbyte.xyz:8000:8001"
TELEMETRY_URL        = "https://oel-telemetry.killerbyte.xyz"

FIRMWARE_INDICATOR = PORTABLE_DIR / "dev_flash" / "sys" / "external" / "libsre.sprx"
GAME_BASE_DIR      = PORTABLE_DIR / "dev_hdd0" / "game"
GAME_INDICATOR     = GAME_BASE_DIR / games.ACTIVE.title_id / "PARAM.SFO"
GAME_USRDIR        = GAME_BASE_DIR / games.ACTIVE.title_id / "USRDIR"
GAME_MANIFEST      = APP_DIR / "data" / "game_manifest.json"


def rpcs3_launch_args() -> list:
    """Extra RPCS3 argv. AppImages need FUSE; without it, fall back to
    --appimage-extract-and-run (handled by the AppImage runtime itself)."""
    if _IS_WIN or RPCS3_EXE.suffix != ".AppImage":
        return []
    if Path("/dev/fuse").exists() and (shutil.which("fusermount3") or shutil.which("fusermount")):
        return []
    return ["--appimage-extract-and-run"]


def rpcs3_log_path() -> Path:
    """RPCS3.log location. fs::get_log_dir is the config dir on Windows but the
    cache dir on Linux, which ignores portable mode."""
    if _IS_WIN:
        return PORTABLE_DIR / "log" / "RPCS3.log"
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.environ.get("HOME", "."), ".cache")
    return Path(cache) / "rpcs3" / "RPCS3.log"


def gameserver_python() -> Path:
    """Interpreter for the game server. On Linux this is a dedicated copy of
    the bundled python so cap_net_bind_service (ports 80/443) is granted to it
    alone, never to the GUI interpreter."""
    if not _IS_WIN:
        cand = APP_DIR / "python" / "bin" / "python3-gameserver"
        if cand.exists():
            return cand
    return Path(PYTHON_EXE)


def privileged_port_command() -> str:
    """The shell command that lets the game server bind ports 80 and 443."""
    py = gameserver_python()
    if py.name == "python3-gameserver":
        return f"sudo setcap cap_net_bind_service=+ep '{py}'"
    return "sudo sysctl net.ipv4.ip_unprivileged_port_start=80"


def privileged_port_help() -> str:
    """Explanation for the Linux <1024 port restriction (ports 80/443)."""
    msg = ("The game server must listen on ports 80 and 443, which Linux "
           "reserves for privileged processes.\n\n"
           "Run this once in a terminal, then launch again:\n\n"
           f"{privileged_port_command()}")
    if gameserver_python().name != "python3-gameserver":
        msg += ("\n\nTo make it permanent:\n"
                "echo net.ipv4.ip_unprivileged_port_start=80 | "
                "sudo tee /etc/sysctl.d/99-opeternal.conf")
    return msg
