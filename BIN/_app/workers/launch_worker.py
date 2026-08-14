"""Off-main-thread preparation before RPCS3 launches."""
from PySide6.QtCore import QThread, Signal

from app.paths import (
    RPCN_TSS, TSS_SRC_DIR, RPCS3_TSS, RPCS3_DIR, RPCS3_CFG_DIR, PATCHES_DIR,
    RPCS3_EXE, CUSTOM_CFG, RPCN_YML, rpcs3_launch_args, clean_stale_appimages,
)
from modules import ip_detect, config as cfg_mod, tss as tss_mod


class LaunchWorker(QThread):
    log     = Signal(str)
    failed  = Signal(str)
    done    = Signal(str)  # emits resolved LAN IP

    def __init__(self, rpcn_host: str, rpcn_mode: str, lan_ip_override: str = "",
                 bind_address: str = "", upnp: bool = True, game_fps: int = 30, parent=None):
        super().__init__(parent)
        self.rpcn_host = rpcn_host
        self.rpcn_mode = rpcn_mode
        self.lan_ip_override = lan_ip_override
        self.bind_address = bind_address
        self.upnp = upnp
        self.game_fps = game_fps

    def run(self):
        try:
            for image in clean_stale_appimages():
                self.log.emit(f"Moved a stale RPCS3 build to _old/: {image.name}")

            # IP swap always targets the LAN IP. The local listener handles the
            # remote-server case by forwarding traffic to the real game server.
            if self.lan_ip_override:
                lan_ip = self.lan_ip_override
                self.log.emit(f"LAN IP: {lan_ip} (selected)")
            else:
                self.log.emit("Detecting LAN IP...")
                lan_ip = ip_detect.get_lan_ip()
                self.log.emit(f"LAN IP: {lan_ip}")

            swap_ip   = lan_ip
            rpcn_host = lan_ip if self.rpcn_mode == "self_hosted" else self.rpcn_host

            self.log.emit("Copying TSS files...")
            rpcn_tss = str(RPCN_TSS) if self.rpcn_mode == "self_hosted" else None
            n = tss_mod.copy_tss(str(TSS_SRC_DIR), str(RPCS3_TSS), rpcn_tss)
            self.log.emit(f"TSS: {n}/15 files copied.")

            self.log.emit("Deploying patches...")
            cfg_mod.deploy_patches(str(RPCS3_DIR), str(RPCS3_CFG_DIR), str(PATCHES_DIR))
            cfg_mod.install_gui_assets(str(RPCS3_DIR), str(PATCHES_DIR))

            self.log.emit("Configuring RPCS3...")
            ok = cfg_mod.ensure_custom_config(
                str(RPCS3_DIR), str(RPCS3_CFG_DIR), str(RPCS3_EXE),
                extra_args=rpcs3_launch_args(),
                progress_cb=lambda m: self.log.emit(m),
            )
            if not ok:
                self.failed.emit("RPCS3 did not generate a config within 30 seconds.")
                return
            cfg_mod.patch_game_config(str(CUSTOM_CFG), swap_ip, self.bind_address, self.upnp, self.game_fps)
            self.log.emit("RPCS3 network config patched.")

            self.log.emit("Writing RPCN config...")
            cfg_mod.write_rpcn_config(str(RPCN_YML), rpcn_host)

            self.done.emit(swap_ip)
        except Exception as e:
            self.failed.emit(str(e))
