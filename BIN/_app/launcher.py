"""OP ETERNAL Launcher - OPERATION ETERNAL LIBERATION."""
import glob
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    Qt, QObject, QThread, Signal, QTimer, QUrl,
)
from PySide6.QtGui import QFont
from PySide6.QtNetwork import (
    QNetworkAccessManager, QNetworkRequest, QNetworkReply,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QTabWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QPushButton, QToolButton, QRadioButton, QLineEdit, QGroupBox, QComboBox,
    QTreeWidget, QTreeWidgetItem, QHeaderView,
    QProgressBar, QMessageBox, QFileDialog,
    QSpinBox, QFrame, QSizePolicy, QButtonGroup, QScrollArea,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_IS_WIN     = sys.platform == "win32"
_EXE        = ".exe" if _IS_WIN else ""

APP_DIR     = Path(__file__).parent.resolve()   # _app/
ROOT_DIR    = APP_DIR.parent                    # folder user sees (where TSS/ lives)
RPCS3_DIR   = APP_DIR / "RPCS3"
RPCN_DIR    = APP_DIR / "rpcn"
GAMESERVER_DIR = APP_DIR / "gameserver"
PATCHES_DIR = APP_DIR / "patches"
PYTHON_EXE  = APP_DIR / "python" / "python.exe" if _IS_WIN else APP_DIR / "python" / "bin" / "python3"
RPCS3_EXE   = RPCS3_DIR / f"rpcs3{_EXE}"
RPCN_EXE    = RPCN_DIR / f"rpcn{_EXE}"
GAMESERVER_SCRIPT = GAMESERVER_DIR / "opeternal_listener.py"
GAMESERVER_LOG    = GAMESERVER_DIR / "gameserver.log"
PORTABLE_DIR = RPCS3_DIR / "portable"
RPCN_YML    = PORTABLE_DIR / "config" / "rpcn.yml"
CUSTOM_CFG  = PORTABLE_DIR / "config" / "custom_configs" / "config_NPUB31347.yml"
TSS_SRC_DIR = ROOT_DIR / "TSS"
RPCS3_TSS   = PORTABLE_DIR / "tss"
RPCN_TSS    = RPCN_DIR / "tss_data" / "NPWR04428_00"
SETTINGS_FILE = APP_DIR / "settings.json"

VERSION = "1.0.2.2"

COMMUNITY_RPCN_HOST = "np.rpcs3.net"

FIRMWARE_INDICATOR = PORTABLE_DIR / "dev_flash" / "sys" / "external" / "libsre.sprx"
GAME_INDICATOR     = PORTABLE_DIR / "dev_hdd0"  / "game"             / "NPUB31347" / "PARAM.SFO"
GAME_USRDIR        = PORTABLE_DIR / "dev_hdd0"  / "game"             / "NPUB31347" / "USRDIR"

# Modules live next to this file
sys.path.insert(0, str(APP_DIR))
from modules import ip_detect, config as cfg_mod, tss as tss_mod
from modules import save_editor, tus_saves, processes

# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "rpcn_mode": "official",       # official | self_hosted | custom
    "rpcn_custom_host": "",
    "gameserver_mode": "self_hosted",  # self_hosted | remote
    "gameserver_remote_ip": "",
    "tss_download_url": "",
    "save_editor_folder": "",
    "network_interface": "",       # "" = auto (default route), else explicit IPv4
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

# ---------------------------------------------------------------------------
# Launch worker (runs preparation steps off the main thread)
# ---------------------------------------------------------------------------
class LaunchWorker(QThread):
    log     = Signal(str)
    failed  = Signal(str)
    done    = Signal(str)  # emits resolved LAN IP

    def __init__(self, rpcn_host: str, rpcn_mode: str, lan_ip_override: str = "", parent=None):
        super().__init__(parent)
        self.rpcn_host = rpcn_host
        self.rpcn_mode = rpcn_mode
        self.lan_ip_override = lan_ip_override

    def run(self):
        try:
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
            cfg_mod.deploy_patches(str(RPCS3_DIR), str(PATCHES_DIR))
            cfg_mod.install_gui_assets(str(RPCS3_DIR), str(PATCHES_DIR))

            self.log.emit("Configuring RPCS3...")
            ok = cfg_mod.ensure_custom_config(
                str(RPCS3_DIR), str(RPCS3_EXE),
                progress_cb=lambda m: self.log.emit(m),
            )
            if not ok:
                self.failed.emit("RPCS3 did not generate a config within 30 seconds.")
                return
            cfg_mod.patch_game_config(str(CUSTOM_CFG), swap_ip)
            self.log.emit("RPCS3 network config patched.")

            self.log.emit("Writing RPCN config...")
            cfg_mod.write_rpcn_config(str(RPCN_YML), rpcn_host)

            self.done.emit(swap_ip)
        except Exception as e:
            self.failed.emit(str(e))

# ---------------------------------------------------------------------------
# TSS downloader (async via QNetworkAccessManager)
# ---------------------------------------------------------------------------
class TssDownloader(QObject):
    progress    = Signal(int, int, str)  # (done, total, filename)
    finished    = Signal(list)           # list of error strings

    def __init__(self, base_url: str, dest_dir: str, parent=None):
        super().__init__(parent)
        self._base_url  = base_url.rstrip("/")
        self._dest_dir  = dest_dir
        self._nam       = QNetworkAccessManager(self)
        self._pending   = list(tss_mod.TSS_FILES)
        self._done      = 0
        self._errors: list[str] = []
        self._current_reply: QNetworkReply | None = None

    def start(self):
        self._fetch_next()

    def _fetch_next(self):
        if not self._pending:
            self.finished.emit(self._errors)
            return
        name = self._pending[0]
        url  = f"{self._base_url}/{name}"
        req  = QNetworkRequest(QUrl(url))
        self._current_reply = self._nam.get(req)
        self._current_reply.finished.connect(lambda: self._on_reply(name))

    def _on_reply(self, name: str):
        reply = self._current_reply
        self._pending.pop(0)
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            dest = os.path.join(self._dest_dir, name)
            with open(dest, "wb") as f:
                f.write(bytes(data))
        else:
            self._errors.append(f"{name}: {reply.errorString()}")
        reply.deleteLater()
        self._done += 1
        self.progress.emit(self._done, len(tss_mod.TSS_FILES), name)
        self._fetch_next()

# ---------------------------------------------------------------------------
# Game files checksum worker
# ---------------------------------------------------------------------------
class ChecksumWorker(QThread):
    """SHA-256 of every file under a tree, walked in sorted relative-path order."""

    done = Signal(str)

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self._root = root

    def run(self):
        try:
            h = hashlib.sha256()
            files = sorted(
                (p for p in self._root.rglob("*") if p.is_file()),
                key=lambda p: p.relative_to(self._root).as_posix(),
            )
            for p in files:
                rel = p.relative_to(self._root).as_posix().encode("utf-8")
                # Length-prefix the path so e.g. "a/bc" and "ab/c" cannot collide.
                h.update(len(rel).to_bytes(4, "big"))
                h.update(rel)
                with p.open("rb") as fh:
                    while True:
                        chunk = fh.read(1 << 20)
                        if not chunk:
                            break
                        h.update(chunk)
            self.done.emit(h.hexdigest())
        except OSError as e:
            self.done.emit(f"error: {e}")


# ---------------------------------------------------------------------------
# Play Tab
# ---------------------------------------------------------------------------
class PlayTab(QWidget):
    launch_requested = Signal()

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._rpcn_running = False
        self._checksum_worker: ChecksumWorker | None = None
        self._checksum_done = False
        self._build_ui()
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self.refresh_setup_status)
        self._status_timer.start()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 12)
        root.setSpacing(8)

        # RPCN Server group
        rpcn_grp = QGroupBox("RPCN Server")
        rpcn_layout = QVBoxLayout(rpcn_grp)
        self._rpcn_official   = QRadioButton("Official  (np.rpcs3.net)")
        self._rpcn_selfhosted = QRadioButton("Self-Hosted")
        self._rpcn_custom     = QRadioButton("Custom")
        self._rpcn_group      = QButtonGroup(self)
        for b in (self._rpcn_official, self._rpcn_selfhosted, self._rpcn_custom):
            self._rpcn_group.addButton(b)
            rpcn_layout.addWidget(b)
        rpcn_custom_row = QHBoxLayout()
        rpcn_custom_row.setContentsMargins(20, 0, 0, 0)
        self._rpcn_custom_host = QLineEdit()
        self._rpcn_custom_host.setPlaceholderText("hostname or IP address")
        rpcn_custom_row.addWidget(QLabel("Host:"))
        rpcn_custom_row.addWidget(self._rpcn_custom_host)
        rpcn_layout.addLayout(rpcn_custom_row)
        root.addWidget(rpcn_grp)

        # Game Server group
        gs_grp = QGroupBox("Game Server")
        gs_layout = QVBoxLayout(gs_grp)
        self._gs_selfhosted = QRadioButton("Self-Hosted")
        self._gs_remote     = QRadioButton("Remote")
        self._gs_group      = QButtonGroup(self)
        self._gs_group.addButton(self._gs_selfhosted)
        self._gs_group.addButton(self._gs_remote)

        gs_layout.addWidget(self._gs_selfhosted)
        self._gs_iface_row_widget = QWidget()
        gs_iface_row = QHBoxLayout(self._gs_iface_row_widget)
        gs_iface_row.setContentsMargins(20, 0, 0, 0)
        gs_iface_row.addWidget(QLabel("Network interface:"))
        self._iface_combo = QComboBox()
        gs_iface_row.addWidget(self._iface_combo, 1)
        self._iface_refresh = QPushButton("Refresh")
        self._iface_refresh.setFixedWidth(80)
        self._iface_refresh.clicked.connect(self._refresh_interfaces)
        gs_iface_row.addWidget(self._iface_refresh)
        gs_layout.addWidget(self._gs_iface_row_widget)

        gs_layout.addWidget(self._gs_remote)
        self._gs_remote_row_widget = QWidget()
        gs_remote_row = QHBoxLayout(self._gs_remote_row_widget)
        gs_remote_row.setContentsMargins(20, 0, 0, 0)
        self._gs_remote_ip = QLineEdit()
        self._gs_remote_ip.setPlaceholderText("host  or  host:http_port:https_port")
        gs_remote_row.addWidget(QLabel("Address:"))
        gs_remote_row.addWidget(self._gs_remote_ip)
        gs_layout.addWidget(self._gs_remote_row_widget)

        root.addWidget(gs_grp)
        self._refresh_interfaces()
        self._iface_combo.currentIndexChanged.connect(self._on_iface_changed)

        # Restore saved modes
        rpcn_mode = self._settings.get("rpcn_mode", "official")
        if rpcn_mode == "self_hosted":
            self._rpcn_selfhosted.setChecked(True)
        elif rpcn_mode == "custom":
            self._rpcn_custom.setChecked(True)
        else:
            self._rpcn_official.setChecked(True)
        self._rpcn_custom_host.setText(self._settings.get("rpcn_custom_host", ""))

        gs_mode = self._settings.get("gameserver_mode", "self_hosted")
        if gs_mode == "remote":
            self._gs_remote.setChecked(True)
        else:
            self._gs_selfhosted.setChecked(True)
        self._gs_remote_ip.setText(self._settings.get("gameserver_remote_ip", ""))

        self._update_custom_visibility()
        for b in (self._rpcn_official, self._rpcn_selfhosted, self._rpcn_custom,
                  self._gs_selfhosted, self._gs_remote):
            b.toggled.connect(self._update_custom_visibility)
        for b in (self._rpcn_official, self._rpcn_selfhosted, self._rpcn_custom):
            b.toggled.connect(self._update_rpcn_indicator)

        # Setup / diagnostics checklist
        setup_grp = QGroupBox("Setup")
        sg = QGridLayout(setup_grp)
        sg.setSpacing(4)
        sg.setColumnStretch(2, 1)

        sg.addWidget(QLabel("PS3 firmware"), 0, 0)
        self._fw_status = QLabel()
        sg.addWidget(self._fw_status, 0, 1)
        self._fw_hint = QLabel("Launch RPCS3, then: File > Install Firmware")
        self._fw_hint.setStyleSheet("color: gray; font-style: italic;")
        sg.addWidget(self._fw_hint, 0, 2)

        sg.addWidget(QLabel("Game"), 1, 0)
        self._game_status = QLabel()
        sg.addWidget(self._game_status, 1, 1)
        self._game_hint = QLabel("Launch RPCS3, then: File > Install Packages/Raps")
        self._game_hint.setStyleSheet("color: gray; font-style: italic;")
        sg.addWidget(self._game_hint, 1, 2)
        self._checksum_field = QLineEdit()
        self._checksum_field.setReadOnly(True)
        self._checksum_field.setPlaceholderText("calculating...")
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("monospace")
        self._checksum_field.setFont(mono)
        self._checksum_field.setCursorPosition(0)
        sg.addWidget(self._checksum_field, 1, 2)
        self._checksum_field.setVisible(False)

        sg.addWidget(QLabel("TSS files"), 2, 0)
        self._tss_label = QLabel()
        sg.addWidget(self._tss_label, 2, 1)
        tss_btn_layout = QHBoxLayout()
        self._tss_browse = QPushButton("Browse...")
        self._tss_browse.setFixedWidth(80)
        tss_btn_layout.addStretch()
        tss_btn_layout.addWidget(self._tss_browse)
        sg.addLayout(tss_btn_layout, 2, 2)

        self._tss_hint = QLabel(
            "TSS files will be streamed as needed from the RPCN server. "
            "Does not work with Official RPCN."
        )
        self._tss_hint.setStyleSheet("color: gray; font-style: italic;")
        self._tss_hint.setWordWrap(True)
        self._tss_hint.setVisible(False)
        sg.addWidget(self._tss_hint, 3, 0, 1, 3)

        root.addWidget(setup_grp)
        self._tss_browse.clicked.connect(self._browse_tss)

        root.addStretch()

        # Launch button
        self._launch_btn = QPushButton("Launch")
        f2 = self._launch_btn.font()
        f2.setPointSize(12)
        f2.setBold(True)
        self._launch_btn.setFont(f2)
        self._launch_btn.setFixedHeight(44)
        self._launch_btn.clicked.connect(self.launch_requested)
        root.addWidget(self._launch_btn)
        self.refresh_setup_status()

        # Status row
        status_row = QHBoxLayout()
        self._gs_indicator   = QLabel("Gameserver: stopped")
        self._rpcn_indicator  = QLabel("RPCN: stopped")
        self._rpcs3_indicator = QLabel("RPCS3: stopped")
        for lbl in (self._gs_indicator, self._rpcn_indicator, self._rpcs3_indicator):
            lbl.setStyleSheet("color: gray;")
            status_row.addWidget(lbl)
        status_row.addStretch()
        root.addLayout(status_row)

        self._update_rpcn_indicator()

    def _update_custom_visibility(self):
        self._rpcn_custom_host.setVisible(self._rpcn_custom.isChecked())
        self._gs_iface_row_widget.setVisible(self._gs_selfhosted.isChecked())
        self._gs_remote_row_widget.setVisible(self._gs_remote.isChecked())

    def refresh_setup_status(self):
        fw_ok   = FIRMWARE_INDICATOR.exists()
        game_ok = GAME_INDICATOR.exists()
        n       = tss_mod.count_present(str(TSS_SRC_DIR))
        total   = len(tss_mod.TSS_FILES)
        tss_ok  = (n == total)

        if fw_ok:
            self._fw_status.setText("installed")
            self._fw_status.setStyleSheet("color: green;")
            self._fw_hint.setVisible(False)
        else:
            self._fw_status.setText("not installed")
            self._fw_status.setStyleSheet("color: red;")
            self._fw_hint.setVisible(True)

        if game_ok:
            self._game_status.setText("installed")
            self._game_status.setStyleSheet("color: green;")
            self._game_hint.setVisible(False)
        else:
            self._game_status.setText("not installed")
            self._game_status.setStyleSheet("color: red;")
            self._game_hint.setVisible(True)

        self._tss_label.setText(f"{n} / {total} files")
        self._tss_label.setStyleSheet("color: green;" if tss_ok else "color: gray;")
        self._tss_hint.setVisible(not tss_ok)

        self._refresh_checksum_row()

    def _refresh_checksum_row(self):
        try:
            usrdir_present = GAME_USRDIR.is_dir() and any(GAME_USRDIR.iterdir())
        except OSError:
            usrdir_present = False

        if not (GAME_INDICATOR.exists() and usrdir_present):
            self._checksum_field.setVisible(False)
            return

        self._checksum_field.setVisible(True)
        if not self._checksum_done and self._checksum_worker is None:
            self._checksum_worker = ChecksumWorker(GAME_USRDIR, self)
            self._checksum_worker.done.connect(self._on_checksum_done)
            self._checksum_worker.start()

    def _on_checksum_done(self, digest: str):
        self._checksum_field.setText(digest)
        self._checksum_field.setToolTip(digest)
        self._checksum_field.setCursorPosition(0)
        self._checksum_done = True
        if self._checksum_worker is not None:
            self._checksum_worker.deleteLater()
            self._checksum_worker = None

    def _browse_tss(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder containing TSS files")
        if not folder:
            return
        files = glob.glob(os.path.join(folder, "NPWR04428_00-*.tss"))
        if not files:
            QMessageBox.warning(self, "No TSS files found",
                                "No .tss files found in that folder.")
            return
        os.makedirs(str(TSS_SRC_DIR), exist_ok=True)
        for f in files:
            shutil.copy2(f, str(TSS_SRC_DIR))
        self.refresh_setup_status()

    def get_rpcn_mode(self) -> str:
        if self._rpcn_selfhosted.isChecked():
            return "self_hosted"
        if self._rpcn_custom.isChecked():
            return "custom"
        return "official"

    def get_rpcn_custom_host(self) -> str:
        return self._rpcn_custom_host.text().strip()

    def get_gameserver_mode(self) -> str:
        return "remote" if self._gs_remote.isChecked() else "self_hosted"

    def get_gameserver_remote_ip(self) -> str:
        return self._gs_remote_ip.text().strip()

    def get_lan_ip_override(self) -> str:
        """Return the user-selected LAN IP, or '' if Auto is selected."""
        return self._iface_combo.currentData() or ""

    def _refresh_interfaces(self):
        previous = self._iface_combo.currentData() if self._iface_combo.count() else \
            self._settings.get("network_interface", "")
        self._iface_combo.blockSignals(True)
        self._iface_combo.clear()
        self._iface_combo.addItem("Auto (default route)", "")
        for ip in ip_detect.list_lan_ips():
            self._iface_combo.addItem(ip, ip)
        idx = self._iface_combo.findData(previous) if previous else 0
        self._iface_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._iface_combo.blockSignals(False)

    def _on_iface_changed(self):
        self._settings["network_interface"] = self._iface_combo.currentData() or ""
        save_settings(self._settings)

    def set_process_status(self, name: str, running: bool):
        if name == "rpcn":
            self._rpcn_running = running
            self._update_rpcn_indicator()
            return
        if name == "gameserver":
            lbl = self._gs_indicator
            text = "Gameserver"
        else:
            lbl = self._rpcs3_indicator
            text = "RPCS3"
        if running:
            lbl.setText(f"{text}: running")
            lbl.setStyleSheet("color: green;")
        else:
            lbl.setText(f"{text}: stopped")
            lbl.setStyleSheet("color: gray;")

    def _update_rpcn_indicator(self):
        if self.get_rpcn_mode() != "self_hosted":
            self._rpcn_indicator.setText("RPCN: Remote")
            self._rpcn_indicator.setStyleSheet("color: green;")
        elif self._rpcn_running:
            self._rpcn_indicator.setText("RPCN: running")
            self._rpcn_indicator.setStyleSheet("color: green;")
        else:
            self._rpcn_indicator.setText("RPCN: stopped")
            self._rpcn_indicator.setStyleSheet("color: gray;")

    def set_launch_enabled(self, enabled: bool):
        self._launch_btn.setEnabled(enabled)
        if enabled:
            self.refresh_setup_status()

# ---------------------------------------------------------------------------
# Save Editor sub-tab
# ---------------------------------------------------------------------------
class SaveEditorTab(QWidget):
    restore_staged = Signal()

    _SLOT_IDS = (
        (2, "00000000000000000002"),
        (3, "00000000000000000003"),
        (4, "00000000000000000004"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slot2: save_editor.SaveSlot | None = None
        self._slot3: save_editor.SaveSlot | None = None
        self._slot4: save_editor.SaveSlot | None = None
        self._build_ui()
        self._try_auto_read()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Auto-detect save path
        detect_row = QHBoxLayout()
        self._path_label = QLabel("Save folder: (not detected)")
        self._path_label.setWordWrap(True)
        detect_btn = QPushButton("Browse...")
        detect_btn.setFixedWidth(90)
        detect_row.addWidget(self._path_label, 1)
        detect_row.addWidget(detect_btn)
        root.addLayout(detect_row)
        detect_btn.clicked.connect(self._browse_saves)
        self._auto_detect_saves()

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep)

        # Penalty Rank quick action (always visible)
        pen_row = QHBoxLayout()
        self._penalty_label = QLabel("Penalty Rank: --")
        self._reset_penalty_btn = QPushButton("Reset Penalty Rank")
        self._reset_penalty_btn.setEnabled(False)
        self._reset_penalty_btn.clicked.connect(self._reset_penalty_rank)
        pen_row.addWidget(self._penalty_label, 1)
        pen_row.addWidget(self._reset_penalty_btn)
        root.addLayout(pen_row)

        self._toggle_btn = QToolButton()
        self._toggle_btn.setText("Save editor")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle_btn.setAutoRaise(True)
        self._toggle_btn.toggled.connect(self._toggle_advanced)
        root.addWidget(self._toggle_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self._advanced = QWidget()
        adv_root = QVBoxLayout(self._advanced)
        adv_root.setContentsMargins(0, 0, 0, 0)
        adv_root.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        self._spins: dict[str, QSpinBox] = {}

        slot3_lbl = QLabel("Slot 3")
        slot3_lbl.setStyleSheet("font-weight: bold;")
        form.addRow(slot3_lbl)
        for f in save_editor.fields_for_slot(3):
            spin = QSpinBox()
            spin.setRange(0, min(f["max"], 2_147_483_647))
            spin.setSingleStep(100_000)
            spin.setGroupSeparatorShown(True)
            self._spins[f["arg"]] = spin
            form.addRow(f["label"] + ":", spin)

        form.addRow(QLabel(""))  # spacer

        slot2_lbl = QLabel("Slot 2")
        slot2_lbl.setStyleSheet("font-weight: bold;")
        form.addRow(slot2_lbl)
        for f in save_editor.fields_for_slot(2):
            spin = QSpinBox()
            spin.setRange(0, min(f["max"], 2_147_483_647))
            spin.setSingleStep(1_000)
            spin.setGroupSeparatorShown(True)
            self._spins[f["arg"]] = spin
            form.addRow(f["label"] + ":", spin)

        form.addRow(QLabel(""))  # spacer

        slot4_lbl = QLabel("Slot 4")
        slot4_lbl.setStyleSheet("font-weight: bold;")
        form.addRow(slot4_lbl)
        for f in save_editor.fields_for_slot(4):
            spin = QSpinBox()
            spin.setRange(0, min(f["max"], 2_147_483_647))
            spin.setSingleStep(1)
            spin.setGroupSeparatorShown(True)
            self._spins[f["arg"]] = spin
            form.addRow(f["label"] + ":", spin)

        for spin in self._spins.values():
            spin.setEnabled(False)

        scroll_widget = QWidget()
        scroll_widget.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(scroll_widget)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        adv_root.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        self._read_btn  = QPushButton("Read from Files")
        self._write_btn = QPushButton("Write to Files")
        self._write_btn.setEnabled(False)
        btn_row.addWidget(self._read_btn)
        btn_row.addWidget(self._write_btn)
        adv_root.addLayout(btn_row)

        note = QLabel(
            "This list is a work in progress. Additional fields can be added by editing "
            "modules/save_editor.py and following the instructions inside."
        )
        note.setWordWrap(True)
        adv_root.addWidget(note)

        warn = QLabel("⚠  Back up your saves before writing.")
        warn.setStyleSheet("color: #c0392b;")
        adv_root.addWidget(warn)

        self._advanced.hide()
        root.addWidget(self._advanced, 1)
        # Soaks up empty space when _advanced is hidden; the section's
        # stretch=1 takes the room back when expanded.
        root.addStretch(0)

        self._read_btn.clicked.connect(self._read_saves)
        self._write_btn.clicked.connect(self._write_saves)

    def _toggle_advanced(self, checked: bool):
        self._advanced.setVisible(checked)
        self._toggle_btn.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )

    def _auto_detect_saves(self):
        saved = load_settings().get("save_editor_folder", "")
        if saved and os.path.isdir(saved):
            self._set_save_dir(saved)
            return
        npwr_root = PORTABLE_DIR / "tus" / "NPWR04428_00"
        try:
            npwr_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        matches = sorted(p for p in npwr_root.glob("*") if p.is_dir())
        if matches:
            self._set_save_dir(str(matches[0]))
        else:
            self._save_dir = None
            self._path_label.setText("Save folder: not found (launch the game once first)")

    def _set_save_dir(self, folder: str):
        self._save_dir = folder
        try:
            short = Path(folder).relative_to(APP_DIR.parent)
        except ValueError:
            short = Path(folder)
        self._path_label.setText(f"Save folder: {short}")
        settings = load_settings()
        if settings.get("save_editor_folder") != folder:
            settings["save_editor_folder"] = folder
            save_settings(settings)

    def _browse_saves(self):
        npwr_root = PORTABLE_DIR / "tus" / "NPWR04428_00"
        try:
            npwr_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        start_dir = str(npwr_root if npwr_root.is_dir() else PORTABLE_DIR)
        folder = QFileDialog.getExistingDirectory(
            self, "Select save folder (tus/<comm_id>/<username>)", start_dir
        )
        if folder:
            self._set_save_dir(folder)
            self._try_auto_read()

    def _try_auto_read(self):
        if self._save_dir:
            self._load_slots()

    def _load_slots(self) -> list[str]:
        """Reload every slot from the latest backups. Returns per-slot error strings."""
        self._slot2 = None
        self._slot3 = None
        self._slot4 = None
        backups_dir = os.path.join(self._save_dir, "backups")
        errors = []
        for slot_num, slot20d in self._SLOT_IDS:
            candidates = sorted(glob.glob(os.path.join(backups_dir, f"*_{slot20d}.tdt")))
            if not candidates:
                errors.append(f"Slot {slot_num}: no backup found in {backups_dir}")
                continue
            try:
                slot = save_editor.SaveSlot(slot_num, candidates[-1])
                values = slot.read_all()
                for arg, val in values.items():
                    if arg in self._spins:
                        self._spins[arg].setValue(val)
                        self._spins[arg].setEnabled(True)
                if slot_num == 2:
                    self._slot2 = slot
                elif slot_num == 3:
                    self._slot3 = slot
                else:
                    self._slot4 = slot
            except Exception as e:
                errors.append(f"Slot {slot_num}: {e}")
        any_loaded = any((self._slot2, self._slot3, self._slot4))
        self._write_btn.setEnabled(any_loaded)
        self._reset_penalty_btn.setEnabled(self._slot4 is not None)
        self._refresh_penalty_label()
        return errors

    def _refresh_penalty_label(self):
        if self._slot4 is None:
            self._penalty_label.setText("Penalty Rank: --")
        else:
            val = self._slot4.read_all().get("penalty-rank", 0)
            self._penalty_label.setText(f"Penalty Rank: {val}")

    def _stage_restore(self, slot_obj: save_editor.SaveSlot):
        slot20d = Path(slot_obj._path).stem.split("_")[-1]
        sentinel = os.path.join(self._save_dir, f"{slot20d}.tdt.restore")
        shutil.copy2(slot_obj._path, sentinel)

    def _read_saves(self):
        if not self._save_dir:
            QMessageBox.warning(self, "No save folder", "No save folder selected or detected.")
            return
        errors = self._load_slots()
        if errors:
            QMessageBox.warning(self, "Load errors", "\n".join(errors))
        else:
            QMessageBox.information(self, "Loaded", "Save files read successfully.")

    def _write_saves(self):
        if not self._slot2 and not self._slot3 and not self._slot4:
            QMessageBox.warning(self, "Not loaded", "Read save files first.")
            return
        errors = []
        for slot_num, slot_obj in ((2, self._slot2), (3, self._slot3), (4, self._slot4)):
            if slot_obj is None:
                continue
            for f in save_editor.fields_for_slot(slot_num):
                if f["arg"] in self._spins:
                    try:
                        slot_obj.write_field(f["arg"], self._spins[f["arg"]].value())
                    except Exception as e:
                        errors.append(f"Slot {slot_num} / {f['label']}: {e}")
            try:
                slot_obj.save()
                self._stage_restore(slot_obj)
            except Exception as e:
                errors.append(f"Slot {slot_num} save failed: {e}")
        self._refresh_penalty_label()
        if errors:
            QMessageBox.critical(self, "Write errors", "\n".join(errors))
        else:
            self.restore_staged.emit()
            QMessageBox.information(
                self, "Saved",
                "Save files written and restore staged.\n\n"
                "Boot OP ETERNAL once to apply the changes."
            )

    def _reset_penalty_rank(self):
        if self._slot4 is None:
            QMessageBox.warning(self, "Not loaded", "Slot 4 has not been read yet.")
            return
        ok, msg = self._apply_penalty_reset()
        if not ok:
            QMessageBox.critical(self, "Reset failed", msg)
            return
        QMessageBox.information(
            self, "Penalty Rank reset",
            "Penalty Rank reset to 0 and restore staged.\n\n"
            "Boot OP ETERNAL once to apply the change."
        )

    def _apply_penalty_reset(self) -> tuple[bool, str]:
        if self._slot4 is None:
            return False, "Slot 4 has not been read yet."
        try:
            self._slot4.write_field("penalty-rank", 0)
            self._slot4.save()
            self._stage_restore(self._slot4)
        except Exception as e:
            return False, str(e)
        if "penalty-rank" in self._spins:
            self._spins["penalty-rank"].setValue(0)
        self._refresh_penalty_label()
        self.restore_staged.emit()
        return True, ""

    def peek_latest_penalty(self) -> tuple[int | None, str | None]:
        """Return (penalty_rank, backup_path) for the newest slot 4 backup, else (None, None)."""
        if not self._save_dir:
            return None, None
        backups_dir = os.path.join(self._save_dir, "backups")
        candidates = sorted(glob.glob(os.path.join(backups_dir, "*_00000000000000000004.tdt")))
        if not candidates:
            return None, None
        latest = candidates[-1]
        try:
            slot = save_editor.SaveSlot(4, latest)
            return slot.read_all().get("penalty-rank", 0), latest
        except Exception:
            return None, None

    def reset_penalty_from_latest(self) -> tuple[bool, str]:
        """Reload slot 4 from the latest backup, reset penalty-rank to 0, refresh the UI."""
        if not self._save_dir:
            return False, "No save folder."
        self._load_slots()
        return self._apply_penalty_reset()

# ---------------------------------------------------------------------------
# Backup / Restore sub-tab
# ---------------------------------------------------------------------------
class BackupRestoreTab(QWidget):
    restore_staged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[tus_saves.BackupEntry] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        path_row = QHBoxLayout()
        self._tus_label = QLabel()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(80)
        path_row.addWidget(QLabel("TUS folder:"))
        path_row.addWidget(self._tus_label, 1)
        path_row.addWidget(refresh_btn)
        root.addLayout(path_row)
        refresh_btn.clicked.connect(self._refresh)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Date", "Time", "Slot", "Size"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._tree, 1)

        btn_row = QHBoxLayout()
        self._restore_btn  = QPushButton("Restore Selected")
        self._newgame_btn  = QPushButton("New Game Override")
        btn_row.addWidget(self._restore_btn)
        btn_row.addWidget(self._newgame_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        note = QLabel(
            "Restore: stages selected backup(s), takes effect on next game boot.\n"
            "New Game Override: resets all slots so the game offers a fresh start."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        self._restore_btn.clicked.connect(self._restore_selected)
        self._newgame_btn.clicked.connect(self._new_game_override)

        self._refresh()

    def _tus_root(self) -> str:
        return str(PORTABLE_DIR / "tus")

    def _refresh(self):
        tus_root = self._tus_root()
        short = Path(tus_root).relative_to(APP_DIR.parent) if APP_DIR.parent in Path(tus_root).parents else Path(tus_root)
        self._tus_label.setText(str(short))
        self._tree.clear()
        self._entries = tus_saves.list_backups(tus_root)

        sessions: dict[str, QTreeWidgetItem] = {}
        for entry in self._entries:
            if entry.session not in sessions:
                parent = QTreeWidgetItem(self._tree, [entry.date, entry.time[:5], "", ""])
                f = parent.font(0)
                f.setBold(True)
                parent.setFont(0, f)
                parent.setExpanded(True)
                sessions[entry.session] = parent
            else:
                parent = sessions[entry.session]

            child = QTreeWidgetItem(parent, [
                "", entry.time, entry.slot, f"{entry.size_kb} KB"
            ])
            child.setCheckState(0, Qt.CheckState.Unchecked)
            child.setData(0, Qt.ItemDataRole.UserRole, entry)

        # Allow clicking session header to toggle all children
        self._tree.itemClicked.connect(self._session_click)

    def _session_click(self, item: QTreeWidgetItem, _col: int):
        if item.childCount() == 0:
            return  # leaf
        # Toggle all children to opposite of majority state
        checked = sum(
            1 for i in range(item.childCount())
            if item.child(i).checkState(0) == Qt.CheckState.Checked
        )
        new_state = Qt.CheckState.Unchecked if checked > item.childCount() // 2 else Qt.CheckState.Checked
        for i in range(item.childCount()):
            item.child(i).setCheckState(0, new_state)

    def _collect_checked(self) -> list[tus_saves.BackupEntry]:
        result = []
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            parent = root.child(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    entry = child.data(0, Qt.ItemDataRole.UserRole)
                    result.append(entry)
        return result

    def _restore_selected(self):
        entries = self._collect_checked()
        if not entries:
            QMessageBox.information(self, "Nothing selected", "Check the backups you want to restore.")
            return
        errors = [e for entry in entries for e in [tus_saves.stage_restore(entry)] if e]
        if errors:
            QMessageBox.warning(self, "Restore errors", "\n".join(errors))
        else:
            self.restore_staged.emit()
            QMessageBox.information(
                self, "Staged",
                f"{len(entries)} slot(s) staged for restore.\n\n"
                "Boot OPERATION ETERNAL LIBERATION. RPCS3 will apply the backup automatically.\n"
                "Save in-game to commit the restored data back to RPCN."
            )

    def _new_game_override(self):
        reply = QMessageBox.question(
            self, "New Game Override",
            "This will create temporary files for all known save slots.\n"
            "On next boot, the game will report no save data and offer a fresh start.\n\n"
            "Your cloud save on RPCN is NOT deleted. It will be overwritten only if you save in-game.\n\n"
            "Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        staged, errors = tus_saves.stage_new_game(self._tus_root(), str(RPCN_YML))
        if errors:
            QMessageBox.warning(self, "Errors", "\n".join(errors))
        else:
            self.restore_staged.emit()
            QMessageBox.information(
                self, "Done",
                f"{staged} slot(s) staged.\nBoot OP ETERNAL to start fresh."
            )

# ---------------------------------------------------------------------------
# Saves Tab (hosts Save Editor + Backup/Restore as inner tabs)
# ---------------------------------------------------------------------------
class SavesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        inner = QTabWidget()
        self.editor_tab = SaveEditorTab()
        inner.addTab(self.editor_tab, "Save Editor")
        self.backup_tab = BackupRestoreTab()
        inner.addTab(self.backup_tab, "Backup / Restore")
        layout.addWidget(inner)

# ---------------------------------------------------------------------------
# TSS Tab
# ---------------------------------------------------------------------------
class TssTab(QWidget):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings   = settings
        self._downloader: TssDownloader | None = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        root.addWidget(QLabel("TSS source folder: " + str(TSS_SRC_DIR)))

        self._list = QTreeWidget()
        self._list.setHeaderLabels(["File", "Status"])
        self._list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        self._dl_btn     = QPushButton("Download Missing")
        self._browse_btn = QPushButton("Copy from Folder...")
        btn_row.addWidget(self._dl_btn)
        btn_row.addWidget(self._browse_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status_lbl = QLabel("")
        root.addWidget(self._status_lbl)

        self._dl_btn.clicked.connect(self._start_download)
        self._browse_btn.clicked.connect(self._browse_and_copy)

        self.refresh()

    def refresh(self):
        self._list.clear()
        for name, present in tss_mod.list_status(str(TSS_SRC_DIR)):
            item = QTreeWidgetItem(self._list, [name, "✓ present" if present else "✗ missing"])
            item.setForeground(1, Qt.GlobalColor.darkGreen if present else Qt.GlobalColor.red)

    def _start_download(self):
        url = self._settings.get("tss_download_url", "").strip()
        if not url:
            QMessageBox.warning(
                self, "No download URL",
                "Configure the TSS download URL in the Settings tab first."
            )
            return
        os.makedirs(str(TSS_SRC_DIR), exist_ok=True)
        self._dl_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(tss_mod.TSS_FILES))
        self._progress.setValue(0)
        self._downloader = TssDownloader(url, str(TSS_SRC_DIR), self)
        self._downloader.progress.connect(self._on_dl_progress)
        self._downloader.finished.connect(self._on_dl_finished)
        self._downloader.start()

    def _on_dl_progress(self, done: int, total: int, name: str):
        self._progress.setValue(done)
        self._status_lbl.setText(f"Downloading... {done}/{total}  ({name})")

    def _on_dl_finished(self, errors: list[str]):
        self._dl_btn.setEnabled(True)
        self._progress.setVisible(False)
        self.refresh()
        if errors:
            QMessageBox.warning(self, "Download errors", "\n".join(errors))
        else:
            self._status_lbl.setText("All TSS files downloaded.")

    def _browse_and_copy(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder containing TSS files")
        if not folder:
            return
        files = glob.glob(os.path.join(folder, "NPWR04428_00-*.tss"))
        if not files:
            QMessageBox.warning(self, "No TSS files found",
                                "No .tss files found in that folder.")
            return
        os.makedirs(str(TSS_SRC_DIR), exist_ok=True)
        for f in files:
            shutil.copy2(f, str(TSS_SRC_DIR))
        self.refresh()
        self._status_lbl.setText(f"Copied {len(files)} file(s).")

# ---------------------------------------------------------------------------
# Settings Tab
# ---------------------------------------------------------------------------
class SettingsTab(QWidget):
    saved = Signal(dict)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(10)

        self._tss_url = QLineEdit(self._settings.get("tss_download_url", ""))
        self._tss_url.setPlaceholderText("https://example.com/tss/")
        form.addRow("TSS download URL:", self._tss_url)

        root.addLayout(form)
        root.addStretch()

        btn_row = QHBoxLayout()
        save_btn  = QPushButton("Save Settings")
        reset_btn = QPushButton("Reset to Defaults")
        btn_row.addWidget(save_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        save_btn.clicked.connect(self._save)
        reset_btn.clicked.connect(self._reset)

    def _save(self):
        self._settings["tss_download_url"] = self._tss_url.text().strip()
        save_settings(self._settings)
        self.saved.emit(self._settings)
        QMessageBox.information(self, "Saved", "Settings saved.")

    def _reset(self):
        self._tss_url.clear()

# ---------------------------------------------------------------------------
# Game server log watcher
# ---------------------------------------------------------------------------
class GameServerLogWatcher(QObject):
    """Polls gameserver.log for `ev_save_load_error` (no-save-on-server boot failure)."""

    SAVE_LOAD_ERROR_TOKEN = b"ev_save_load_error"
    POLL_MS = 2000

    save_load_error_seen = Signal()

    def __init__(self, log_path: Path, parent=None):
        super().__init__(parent)
        self._log_path = log_path
        self._pos = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._tick)

    def start(self):
        # Start at EOF; only events written from now on count.
        try:
            self._pos = self._log_path.stat().st_size
        except OSError:
            self._pos = 0
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _tick(self):
        try:
            size = self._log_path.stat().st_size
        except OSError:
            return
        if size < self._pos:
            # Log rotated; restart from the beginning.
            self._pos = 0
        if size <= self._pos:
            return
        try:
            with self._log_path.open("rb") as fh:
                fh.seek(self._pos)
                chunk = fh.read()
        except OSError:
            return
        self._pos += len(chunk)
        if self.SAVE_LOAD_ERROR_TOKEN in chunk:
            self.save_load_error_seen.emit()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class ACILauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings = load_settings()
        self._worker: LaunchWorker | None = None
        self._gameserver  = processes.ManagedProcess("gameserver", self)
        self._rpcn_proc   = processes.ManagedProcess("rpcn", self)
        self._rpcs3_proc  = processes.ManagedProcess("rpcs3", self)

        self._restore_staged = False
        self._save_load_offer_shown = False
        self._last_penalty_check_path: str | None = None

        for proc, name in ((self._gameserver, "gameserver"),
                           (self._rpcn_proc,  "rpcn"),
                           (self._rpcs3_proc, "rpcs3")):
            proc.started.connect(lambda n=name: self._play_tab.set_process_status(n, True))
            proc.stopped.connect(lambda _ec, n=name: self._play_tab.set_process_status(n, False))

        # Refresh diagnostics after RPCS3 exits so firmware/game installs are detected.
        # Also clean up any dangling .restore sentinels and reset the staged flag.
        self._rpcs3_proc.stopped.connect(self._on_rpcs3_stopped)

        self.setWindowTitle(f"OPERATION ETERNAL LIBERATION {VERSION}")
        self.setFixedSize(720, 660)
        self._build_ui()

        self._log_watcher = GameServerLogWatcher(GAMESERVER_LOG, self)
        self._log_watcher.save_load_error_seen.connect(self._on_save_load_error)
        self._log_watcher.start()

        # Let the window paint before the first penalty check.
        QTimer.singleShot(800, self._check_penalty_rank)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        self._play_tab = PlayTab(self._settings)
        self._saves_tab = SavesTab()
        self._tss_tab   = TssTab(self._settings)
        self._settings_tab = SettingsTab(self._settings)

        tabs.addTab(self._play_tab,     "Play")
        tabs.addTab(self._saves_tab,    "Saves")
        tabs.addTab(self._tss_tab,      "TSS Files")
        tabs.addTab(self._settings_tab, "Settings")
        layout.addWidget(tabs)

        self._play_tab.launch_requested.connect(self._start_launch)
        self._settings_tab.saved.connect(self._on_settings_saved)
        self._saves_tab.backup_tab.restore_staged.connect(lambda: setattr(self, "_restore_staged", True))
        self._saves_tab.editor_tab.restore_staged.connect(lambda: setattr(self, "_restore_staged", True))

    def _resolve_rpcn_host(self) -> str:
        mode = self._play_tab.get_rpcn_mode()
        if mode == "self_hosted":
            return "127.0.0.1"
        if mode == "custom":
            return self._play_tab.get_rpcn_custom_host()
        return COMMUNITY_RPCN_HOST

    def _start_launch(self):
        issues = []
        if not FIRMWARE_INDICATOR.exists():
            issues.append("PS3 firmware is not installed.")
        if not GAME_INDICATOR.exists():
            issues.append("OPERATION ETERNAL LIBERATION is not installed.")
        if issues:
            msg = "The following items are missing:\n\n" + "\n".join(f"  - {i}" for i in issues)
            msg += "\n\nYou can still open RPCS3 to complete setup, but the game will not work online until everything is ready."
            reply = QMessageBox.warning(
                self, "Setup incomplete", msg,
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Ok:
                return

        rpcn_mode = self._play_tab.get_rpcn_mode()
        gs_mode   = self._play_tab.get_gameserver_mode()
        self._settings["rpcn_mode"]            = rpcn_mode
        self._settings["rpcn_custom_host"]     = self._play_tab.get_rpcn_custom_host()
        self._settings["gameserver_mode"]      = gs_mode
        self._settings["gameserver_remote_ip"] = self._play_tab.get_gameserver_remote_ip()
        save_settings(self._settings)

        rpcn_host = self._resolve_rpcn_host()
        if rpcn_mode == "custom" and not rpcn_host:
            QMessageBox.warning(self, "No RPCN server",
                                "Enter a server address in the Custom field.")
            return

        gs_remote_ip = self._play_tab.get_gameserver_remote_ip()
        if gs_mode == "remote":
            if not gs_remote_ip:
                QMessageBox.warning(self, "No game server",
                                    "Enter the remote game server address.")
                return
            try:
                parse_remote_addr(gs_remote_ip)
            except ValueError as e:
                QMessageBox.warning(self, "Invalid address",
                                    f"Could not parse '{gs_remote_ip}': {e}\n\n"
                                    "Expected: host  or  host:http_port:https_port")
                return

        self._save_load_offer_shown = False
        self._play_tab.set_launch_enabled(False)
        lan_ip_override = self._play_tab.get_lan_ip_override()
        self._worker = LaunchWorker(rpcn_host, rpcn_mode, lan_ip_override, self)
        self._worker.log.connect(self._on_worker_log)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.done.connect(self._on_worker_done)
        self._worker.start()

    def _on_worker_log(self, msg: str):
        # Show brief status in window title while preparing
        self.setWindowTitle(f"OPERATION ETERNAL LIBERATION {VERSION} - {msg}")

    def _on_worker_failed(self, msg: str):
        self.setWindowTitle(f"OPERATION ETERNAL LIBERATION {VERSION}")
        self._play_tab.set_launch_enabled(True)
        QMessageBox.critical(self, "Launch failed", msg)

    def _on_worker_done(self, swap_ip: str):
        self.setWindowTitle(f"OPERATION ETERNAL LIBERATION {VERSION}")
        rpcn_mode = self._settings.get("rpcn_mode", "official")
        gs_mode   = self._settings.get("gameserver_mode", "self_hosted")

        gs_args = [str(GAMESERVER_SCRIPT), "--bind-ip", swap_ip]
        if gs_mode == "remote":
            try:
                host, http_p, https_p = parse_remote_addr(
                    self._settings.get("gameserver_remote_ip", "")
                )
                gs_args += [
                    "--forward", host,
                    "--forward-http-port",  str(http_p),
                    "--forward-https-port", str(https_p),
                ]
            except ValueError as e:
                QMessageBox.warning(self, "Invalid address",
                                    f"Could not parse remote address: {e}")
                self._play_tab.set_launch_enabled(True)
                return

        if not processes.is_port_open(swap_ip):
            ok = self._gameserver.launch(
                str(PYTHON_EXE),
                gs_args,
                cwd=str(GAMESERVER_DIR),
                new_console=True,
            )
            if not ok:
                QMessageBox.warning(self, "Gameserver", "Could not start the game server.")

        if rpcn_mode == "self_hosted" and not self._rpcn_proc.is_running():
            QTimer.singleShot(2000, lambda: self._rpcn_proc.launch(
                str(RPCN_EXE), [], cwd=str(RPCN_DIR), new_console=True,
            ))

        if not self._rpcs3_proc.is_running():
            if not self._restore_staged:
                tus_saves.cleanup_restore_sentinels(str(PORTABLE_DIR / "tus"))
            self._restore_staged = False
            self._rpcs3_proc.launch(str(RPCS3_EXE), [], cwd=str(RPCS3_DIR))

        self._play_tab.set_launch_enabled(True)
        self._tss_tab.refresh()

    def _on_rpcs3_stopped(self, _exit_code: int):
        self._play_tab.refresh_setup_status()
        tus_saves.cleanup_restore_sentinels(str(PORTABLE_DIR / "tus"))
        self._restore_staged = False
        # Pick up any backups written this session before the penalty check.
        self._saves_tab.editor_tab._try_auto_read()
        self._check_penalty_rank()

    def _check_penalty_rank(self):
        editor = self._saves_tab.editor_tab
        rank, path = editor.peek_latest_penalty()
        if rank is None or path is None:
            return
        if rank <= 0:
            self._last_penalty_check_path = path
            return
        if path == self._last_penalty_check_path:
            return
        self._last_penalty_check_path = path
        reply = QMessageBox.question(
            self, "Penalty Rank detected",
            f"Your latest save shows a Penalty Rank of {rank}.\n\n"
            "Would you like to reset it to 0?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        confirm = QMessageBox.warning(
            self, "Confirm Penalty Rank reset",
            "This will write Penalty Rank = 0 to your local save and stage it "
            "for the game to apply on next boot. The change syncs to RPCN the "
            "next time the game saves.\n\n"
            "Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        ok, msg = editor.reset_penalty_from_latest()
        if not ok:
            QMessageBox.warning(self, "Reset failed", msg)
            return
        self._restore_staged = True
        QMessageBox.information(
            self, "Done",
            "Penalty Rank reset to 0 and restore staged.\n"
            "Boot OP ETERNAL once to apply the change."
        )

    def _on_save_load_error(self):
        if self._save_load_offer_shown:
            return
        self._save_load_offer_shown = True
        reply = QMessageBox.question(
            self, "Save load error detected",
            "The game just reported a save load error.\n\n"
            "Usually this means your account has no save on this server yet "
            "and the game cannot get past the initial connect screen until a "
            "fresh save is staged.\n\n"
            "Run a New Game Override now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        confirm = QMessageBox.warning(
            self, "Confirm New Game Override",
            "This stages empty save slots that the game will treat as a fresh "
            "start. If you save in-game after this, the empty state writes to "
            "RPCN and any existing cloud save is overwritten.\n\n"
            "If you have a save you want to keep, cancel and use "
            "Saves > Backup / Restore instead.\n\n"
            "Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        staged, errors = tus_saves.stage_new_game(str(PORTABLE_DIR / "tus"), str(RPCN_YML))
        self._restore_staged = True
        if errors:
            QMessageBox.warning(self, "Errors", "\n".join(errors))
        else:
            QMessageBox.information(
                self, "Done",
                f"{staged} slot(s) staged.\n"
                "Reboot OPERATION ETERNAL LIBERATION to start fresh."
            )

    def _on_settings_saved(self, settings: dict):
        self._settings = settings
        self._tss_tab._settings = settings

    def closeEvent(self, event):
        self._log_watcher.stop()
        for proc in (self._gameserver, self._rpcn_proc, self._rpcs3_proc):
            proc.stop()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("OPERATION ETERNAL LIBERATION")
    window = ACILauncher()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
