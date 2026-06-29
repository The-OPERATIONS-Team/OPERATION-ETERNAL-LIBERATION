"""Launcher settings persistence and network-address helpers."""
import ipaddress
import json

from app.paths import SETTINGS_FILE, RELEASE_CHANNEL
from modules import ip_detect

_DEFAULTS = {
    "rpcn_mode": "official",       # official | self_hosted | custom
    "rpcn_custom_host": "",
    "gameserver_mode": "self_hosted",  # self_hosted | remote | operations
    "gameserver_remote_ip": "",
    "rpcs3_bind_address": "",       # "" = RPCS3 default (0.0.0.0, all interfaces)
    "rpcs3_upnp": True,             # enable RPCS3 UPnP port forwarding (opt-out)
    "tss_download_url": "",
    "save_editor_folder": "",
    "network_interface": "",       # "" = auto (default route), else explicit IPv4
    "enable_telemetry": False,
    "telemetry_client_id": "",
    "auto_check_updates": RELEASE_CHANNEL == "experimental",
    "update_channel": RELEASE_CHANNEL,
    "desktop_shortcut_offered": False,   # Linux only; installer covers Windows
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return {**_DEFAULTS, **data}
        except Exception:
            pass
    return dict(_DEFAULTS)


def save_settings(s: dict):
    SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")


def parse_remote_addr(s: str) -> tuple[str, int, int]:
    """Parse 'host', 'host:port', or 'host:httpport:httpsport'.

    Returns (host, http_port, https_port). Defaults: 80 / 443.
    Raises ValueError if the host is empty or any port is not a positive int.
    """
    parts = [p.strip() for p in s.split(":")]
    host = parts[0]
    if not host:
        raise ValueError("empty host")

    def _port(idx: int, default: int) -> int:
        if len(parts) <= idx or not parts[idx]:
            return default
        n = int(parts[idx])
        if not (0 < n < 65536):
            raise ValueError(f"port out of range: {n}")
        return n

    http_p  = _port(1, 80)
    https_p = _port(2, 443)
    return host, http_p, https_p


# WireGuard relay tunnel subnet (see WORK/docs/networking/rpcn-ports-relay.md).
RELAY_SUBNET = "10.99.99.0/24"


def is_relay_addr(ip: str) -> bool:
    """True if `ip` is an IPv4 inside RELAY_SUBNET (a WireGuard tunnel address)."""
    if not ip:
        return False
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(RELAY_SUBNET)
    except ValueError:
        return False


def relay_bind_ip() -> str | None:
    """First live LAN IP inside RELAY_SUBNET (the WireGuard tunnel IP), or None."""
    for ip in ip_detect.list_lan_ips():
        if is_relay_addr(ip):
            return ip
    return None
