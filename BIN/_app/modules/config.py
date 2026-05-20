"""RPCS3 config patching and RPCN config management."""
import os
import re
import shutil
import subprocess
import time


def deploy_patches(
    rpcs3_data_dir: str,
    rpcs3_config_dir: str,
    patches_dir: str
):
    patches_dest = os.path.join(rpcs3_data_dir, "patches")
    os.makedirs(patches_dest, exist_ok=True)
    os.makedirs(rpcs3_config_dir, exist_ok=True)
    shutil.copy2(
        os.path.join(patches_dir, "imported_patch.yml"),
        os.path.join(patches_dest, "imported_patch.yml"),
    )
    shutil.copy2(
        os.path.join(patches_dir, "patch_config.yml"),
        os.path.join(rpcs3_config_dir, "patch_config.yml"),
    )


_GUI_PRESERVE = {"CurrentSettings.ini", "persistent_settings.dat"}


def install_gui_assets(rpcs3_data_dir: str, patches_dir: str):
    """Deploy GuiConfigs themes and Icons/ui assets; never overwrite user settings files."""
    mappings = [
        (os.path.join(patches_dir, "GuiConfigs"),
         os.path.join(rpcs3_data_dir, "GuiConfigs")),
        (os.path.join(patches_dir, "Icons", "ui"),
         os.path.join(rpcs3_data_dir, "Icons", "ui")),
    ]
    for src, dst in mappings:
        if not os.path.exists(src):
            continue
        for dirpath, _dirs, files in os.walk(src):
            rel_dir = os.path.relpath(dirpath, src)
            dst_dir = os.path.join(dst, rel_dir) if rel_dir != "." else dst
            os.makedirs(dst_dir, exist_ok=True)
            for name in files:
                if name in _GUI_PRESERVE:
                    continue
                shutil.copy2(os.path.join(dirpath, name), os.path.join(dst_dir, name))


def ensure_custom_config(
    rpcs3_dir: str,
    rpcs3_config_dir: str,
    rpcs3_exe: str,
    timeout: int = 30,
    progress_cb=None,
) -> bool:
    """Create the per-game custom config if it doesn't exist yet.

    Launches RPCS3 briefly to generate config.yml on first run.
    Returns True on success, False if config.yml never appeared.
    """
    cfg_dir    = os.path.join(rpcs3_config_dir, "custom_configs")
    cfg_path   = os.path.join(cfg_dir, "config_NPUB31347.yml")
    global_cfg = os.path.join(rpcs3_config_dir, "config.yml")
    os.makedirs(cfg_dir, exist_ok=True)

    if os.path.exists(cfg_path):
        return True

    if not os.path.exists(global_cfg):
        if progress_cb:
            progress_cb("No RPCS3 config found — launching briefly to generate one...")
        proc = subprocess.Popen([rpcs3_exe], cwd=rpcs3_dir)
        for _ in range(timeout):
            if os.path.exists(global_cfg):
                break
            time.sleep(1)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        if not os.path.exists(global_cfg):
            return False
        if progress_cb:
            progress_cb("Config generated.")
    os.path.join(global_cfg, cfg_path)
    shutil.copy2(global_cfg, cfg_path)
    return True


def patch_game_config(cfg_path: str, lan_ip: str):
    """Patch the three network keys in the per-game custom config in-place."""
    with open(cfg_path, "r", encoding="utf-8") as f:
        content = f.read()

    swap = f"dev-wind.siliconstudio.co.jp={lan_ip}&&aci.vs765.nbgi-amnet.jp={lan_ip}"
    content = re.sub(r"Internet enabled:.*",  "Internet enabled: Connected", content)
    content = re.sub(r"PSN status:.*",        "PSN status: RPCN",           content)
    content = re.sub(r"IP swap list:.*",      f"IP swap list: {swap}",       content)

    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(content)


_OFFICIAL_NAME  = "Official RPCN Server"
_OFFICIAL_HOST  = "np.rpcs3.net"


def _host_display_name(host: str) -> str:
    return f"Self-Hosted ({host})"


_HOSTS_SEP = "|||"  # separates entries; within an entry: name|host


def _parse_hosts(raw: str) -> list[tuple[str, str]]:
    """Parse RPCS3 Hosts string into (display_name, host) pairs."""
    entries = []
    for entry in raw.split(_HOSTS_SEP):
        entry = entry.strip().strip('"')
        if "|" in entry:
            name, h = entry.split("|", 1)
            if name.strip() and h.strip():
                entries.append((name.strip(), h.strip()))
    return entries


def _build_hosts(raw: str, active_host: str) -> str:
    """Return sanitized Hosts string, ensuring official and active entries are present."""
    entries = _parse_hosts(raw)
    seen = {h for _, h in entries}

    if _OFFICIAL_HOST not in seen:
        entries.insert(0, (_OFFICIAL_NAME, _OFFICIAL_HOST))
        seen.add(_OFFICIAL_HOST)

    if active_host not in seen:
        entries.append((_host_display_name(active_host), active_host))

    return _HOSTS_SEP.join(f"{name}|{h}" for name, h in entries)


def write_rpcn_config(rpcn_yml_path: str, host: str):
    """Write rpcn.yml, setting host as the active server.

    First run: creates the file with the official RPCN server in the Hosts list.
    Subsequent runs: updates Host: and sanitizes the Hosts list (deduplicates,
    ensures the official entry is present) without touching credentials.
    """
    if not os.path.exists(rpcn_yml_path):
        os.makedirs(os.path.dirname(rpcn_yml_path), exist_ok=True)
        hosts_str = _build_hosts("", host)
        content = (
            f"Version: 2\n"
            f"Host: {host}\n"
            f'NPID: ""\n'
            f'Password: ""\n'
            f'Token: ""\n'
            f"Hosts: {hosts_str}\n"
            f"Experimental IPv6 support: false\n"
        )
        with open(rpcn_yml_path, "w", encoding="utf-8") as f:
            f.write(content)
        return

    with open(rpcn_yml_path, "r", encoding="utf-8") as f:
        content = f.read()

    content = re.sub(r"^Host:.*$", f"Host: {host}", content, flags=re.MULTILINE)

    # Update Hosts: deduplicate and ensure active host is present.
    # Use DOTALL to handle multi-line values left by old buggy writes.
    m = re.search(r'^Hosts:\s*"?(.*?)"?\s*$', content, flags=re.MULTILINE | re.DOTALL)
    if m:
        new_line = f"Hosts: {_build_hosts(m.group(1), host)}"
        content = content[:m.start()] + new_line + content[m.end():]

    with open(rpcn_yml_path, "w", encoding="utf-8") as f:
        f.write(content)
