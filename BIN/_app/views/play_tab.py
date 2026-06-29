"""Play tab: connection setup, diagnostics, verification, and launch.

The polling, verification, and launch-gating logic lives in PlayViewModel.
"""
import glob
import os
import shutil
import uuid

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QRadioButton, QLineEdit, QGroupBox, QComboBox,
    QCheckBox, QButtonGroup, QMessageBox, QFileDialog, QStyle,
)

from app.paths import TSS_SRC_DIR
from app.settings import save_settings, is_relay_addr, relay_bind_ip
from modules import games, ip_detect
from viewmodels.play_vm import PlayViewModel
from views.game_verify_dialog import GameVerifyDialog


class PlayTab(QWidget):
    launch_requested = Signal()

    _VERIFY_FAIL_TOOLTIP = (
        "Verification of at least one of your game files has failed. "
        "You may encounter issues during gameplay. Make sure to have installed "
        "your game and patches completely and in the correct order."
    )

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._rpcn_running = False
        self._relay_bind_checked = False
        self._vm = PlayViewModel(self)
        self._vm.setup_status.connect(self._render_setup_status)
        self._vm.verify_started.connect(self._on_verify_started)
        self._vm.verify_progress.connect(self._on_verify_progress)
        self._vm.verify_finished.connect(self._on_verify_finished)
        self._vm.verify_failed.connect(self._on_verify_failed)
        self._build_ui()
        self._vm.start_polling()

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
        self._gs_operations = QRadioButton("-OPERATIONS- Team server")
        self._gs_selfhosted = QRadioButton("Self-Hosted")
        self._gs_remote     = QRadioButton("Remote")
        self._gs_group      = QButtonGroup(self)
        self._gs_group.addButton(self._gs_operations)
        self._gs_group.addButton(self._gs_selfhosted)
        self._gs_group.addButton(self._gs_remote)

        gs_layout.addWidget(self._gs_operations)
        self._gs_ops_panel = QWidget()
        ops_panel_layout = QVBoxLayout(self._gs_ops_panel)
        ops_panel_layout.setContentsMargins(20, 0, 0, 0)
        ops_info = QLabel("Connects to the -OPERATIONS- community server.")
        ops_info.setStyleSheet("color: gray; font-style: italic;")
        ops_panel_layout.addWidget(ops_info)
        self._telemetry_check = QCheckBox("Share RPCS3 logs to help improve the emulator (anonymized)")
        self._telemetry_check.setChecked(bool(self._settings.get("enable_telemetry", False)))
        self._telemetry_check.toggled.connect(self._on_telemetry_changed)
        ops_panel_layout.addWidget(self._telemetry_check)
        gs_layout.addWidget(self._gs_ops_panel)

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

        # RPCS3 group
        rpcs3_grp = QGroupBox("RPCS3")
        rpcs3_layout = QVBoxLayout(rpcs3_grp)
        bind_row = QHBoxLayout()
        bind_row.addWidget(QLabel("Bind address:"))
        self._rpcs3_bind_combo = QComboBox()
        bind_row.addWidget(self._rpcs3_bind_combo, 1)
        rpcs3_layout.addLayout(bind_row)

        self._upnp_check = QCheckBox("Enable UPnP (automatic port forwarding)")
        self._upnp_check.setChecked(bool(self._settings.get("rpcs3_upnp", True)))
        self._upnp_check.toggled.connect(self._on_upnp_changed)
        rpcs3_layout.addWidget(self._upnp_check)
        root.addWidget(rpcs3_grp)

        self._refresh_interfaces()
        self._iface_combo.currentIndexChanged.connect(self._on_iface_changed)
        self._rpcs3_bind_combo.currentIndexChanged.connect(self._on_rpcs3_bind_changed)

        # Restore saved modes
        rpcn_mode = self._settings.get("rpcn_mode", "official")
        if rpcn_mode == "self_hosted":
            self._rpcn_selfhosted.setChecked(True)
        elif rpcn_mode == "custom":
            self._rpcn_custom.setChecked(True)
        else:
            self._rpcn_official.setChecked(True)
        self._rpcn_custom_host.setText(self._settings.get("rpcn_custom_host", ""))

        gs_mode = self._settings.get("gameserver_mode", "operations")
        if gs_mode == "remote":
            self._gs_remote.setChecked(True)
        elif gs_mode == "operations":
            self._gs_operations.setChecked(True)
        else:
            self._gs_selfhosted.setChecked(True)
        self._gs_remote_ip.setText(self._settings.get("gameserver_remote_ip", ""))

        self._update_custom_visibility()
        for b in (self._rpcn_official, self._rpcn_selfhosted, self._rpcn_custom,
                  self._gs_selfhosted, self._gs_remote, self._gs_operations):
            b.toggled.connect(self._update_custom_visibility)
            b.toggled.connect(self._on_mode_toggled)
        for b in (self._rpcn_official, self._rpcn_selfhosted, self._rpcn_custom):
            b.toggled.connect(self._update_rpcn_indicator)
        self._rpcn_custom_host.editingFinished.connect(self._persist_connection_settings)
        self._gs_remote_ip.editingFinished.connect(self._persist_connection_settings)

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

        # Game-file verification controls.
        self._verify_row = QWidget()
        verify_layout = QHBoxLayout(self._verify_row)
        verify_layout.setContentsMargins(0, 0, 0, 0)
        self._verify_btn = QPushButton("Verify game files")
        self._verify_warning = QLabel()
        warn_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        self._verify_warning.setPixmap(warn_icon.pixmap(16, 16))
        self._verify_warning.setToolTip(self._VERIFY_FAIL_TOOLTIP)
        self._verify_warning.setVisible(False)
        self._verify_ok = QLabel()
        ok_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        self._verify_ok.setPixmap(ok_icon.pixmap(16, 16))
        self._verify_ok.setToolTip("All game files verified.")
        self._verify_ok.setVisible(False)
        self._verify_progress = QLabel("Checking...")
        self._verify_progress.setVisible(False)
        verify_layout.addWidget(self._verify_btn)
        verify_layout.addWidget(self._verify_warning)
        verify_layout.addWidget(self._verify_ok)
        verify_layout.addWidget(self._verify_progress)
        verify_layout.addStretch()
        sg.addWidget(self._verify_row, 1, 2)
        self._verify_row.setVisible(False)
        self._verify_btn.clicked.connect(self._open_verify_dialog)

        # Shown instead of the verify row when an unsupported edition (EU/JP) is detected.
        self._unsupported_row = QWidget()
        unsup_layout = QHBoxLayout(self._unsupported_row)
        unsup_layout.setContentsMargins(0, 0, 0, 0)
        unsup_icon = QLabel()
        unsup_icon.setPixmap(warn_icon.pixmap(16, 16))
        unsup_msg = QLabel("This game edition is not supported yet. "
                           "Compatibility is planned in the future versions.")
        unsup_msg.setWordWrap(True)
        unsup_layout.addWidget(unsup_icon)
        unsup_layout.addWidget(unsup_msg, 1)
        sg.addWidget(self._unsupported_row, 1, 2)
        self._unsupported_row.setVisible(False)

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
        self._launch_btn.clicked.connect(self._on_launch_clicked)
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
        self._gs_ops_panel.setVisible(self._gs_operations.isChecked())

    def refresh_setup_status(self):
        self._vm.refresh()

    def _render_setup_status(self, status):
        if status.fw_ok:
            self._fw_status.setText("installed")
            self._fw_status.setStyleSheet("color: green;")
            self._fw_hint.setVisible(False)
        else:
            self._fw_status.setText("not installed")
            self._fw_status.setStyleSheet("color: red;")
            self._fw_hint.setVisible(True)

        if status.game == "missing":
            self._game_status.setText("not installed")
            self._game_status.setStyleSheet("color: red;")
            self._game_hint.setVisible(True)
            self._verify_row.setVisible(False)
            self._unsupported_row.setVisible(False)
        elif status.game == "unsupported":
            self._game_status.setText(f"{status.region} edition not supported")
            self._game_status.setStyleSheet("color: red;")
            self._game_hint.setVisible(False)
            self._verify_row.setVisible(False)
            self._unsupported_row.setVisible(True)
        else:
            self._game_status.setText("installed")
            self._game_status.setStyleSheet("color: green;")
            self._game_hint.setVisible(False)
            self._unsupported_row.setVisible(False)
            self._verify_row.setVisible(True)

        tss_ok = (status.tss_present == status.tss_total)
        self._tss_label.setText(f"{status.tss_present} / {status.tss_total} files")
        self._tss_label.setStyleSheet("color: green;" if tss_ok else "color: gray;")
        self._tss_hint.setVisible(not tss_ok)

    def _on_verify_started(self):
        self._verify_ok.setVisible(False)
        self._verify_warning.setVisible(False)
        self._verify_progress.setText("Checking...")
        self._verify_progress.setVisible(True)

    def _on_verify_progress(self, current: int, total: int):
        self._verify_progress.setText(f"Checking... {current}/{total}")

    def _on_verify_finished(self, result):
        self._verify_progress.setVisible(False)
        self._verify_warning.setToolTip(self._VERIFY_FAIL_TOOLTIP)
        self._verify_warning.setVisible(not result.ok)
        self._verify_ok.setVisible(result.ok)

    def _on_verify_failed(self, error: str):
        self._verify_progress.setVisible(False)
        self._verify_ok.setVisible(False)
        self._verify_warning.setToolTip(
            "Game file verification could not complete:\n"
            f"{error}\n\n"
            "Click \"Verify game files\" to try again."
        )
        self._verify_warning.setVisible(True)

    def _open_verify_dialog(self):
        result = self._vm.verify_result
        if result is not None:
            GameVerifyDialog(result, self).exec()
            return
        if self._vm.verify_errored and not self._vm.verify_running:
            self._vm.force_verify()
            return
        QMessageBox.information(
            self, "Verifying game files",
            "Game files are still being verified. Please try again in a moment.")

    def _on_launch_clicked(self):
        # Gate the launch on the detected edition and the verification result.
        decision = self._vm.launch_decision()
        if decision == PlayViewModel.LAUNCH_UNSUPPORTED:
            answer = QMessageBox.warning(
                self, "Game edition not supported",
                "This game edition is not supported yet. Compatibility is planned "
                "in the future versions.\n\nLaunch anyways?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        elif decision == PlayViewModel.LAUNCH_VERIFY_UNFINISHED:
            answer = QMessageBox.question(
                self, "Verification not finished",
                "Game file verification hasn't finished yet. Launch anyways?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        elif decision == PlayViewModel.LAUNCH_VERIFY_FAILED:
            answer = QMessageBox.warning(
                self, "Game files may be incomplete",
                "Verification of at least one of your game files has failed. "
                "You may encounter issues during gameplay. Make sure to have "
                "installed your game and patches completely and in the correct "
                "order.\n\nUse \"Verify game files\" for details. Launch anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        elif decision == PlayViewModel.LAUNCH_VERIFY_ERROR:
            answer = QMessageBox.warning(
                self, "Verification incomplete",
                "Game file verification could not complete, so your install "
                "could not be checked. You may encounter issues during "
                "gameplay.\n\nLaunch anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.launch_requested.emit()

    def get_game_hash(self) -> str:
        return self._vm.get_game_hash()

    def _browse_tss(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder containing TSS files")
        if not folder:
            return
        files = glob.glob(os.path.join(folder, f"{games.ACTIVE.comm_id}-*.tss"))
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
        if self._gs_operations.isChecked():
            return "operations"
        if self._gs_remote.isChecked():
            return "remote"
        return "self_hosted"

    def get_gameserver_remote_ip(self) -> str:
        return self._gs_remote_ip.text().strip()

    def get_lan_ip_override(self) -> str:
        """Return the user-selected LAN IP, or '' if Auto is selected."""
        return self._iface_combo.currentData() or ""

    def _refresh_interfaces(self):
        lan_ips = ip_detect.list_lan_ips()

        previous = self._iface_combo.currentData() if self._iface_combo.count() else \
            self._settings.get("network_interface", "")
        self._iface_combo.blockSignals(True)
        self._iface_combo.clear()
        self._iface_combo.addItem("Auto (default route)", "")
        for ip in lan_ips:
            self._iface_combo.addItem(ip, ip)
        idx = self._iface_combo.findData(previous) if previous else 0
        self._iface_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._iface_combo.blockSignals(False)

        prev_bind = self._rpcs3_bind_combo.currentData() if self._rpcs3_bind_combo.count() \
            else self._settings.get("rpcs3_bind_address", "")
        self._rpcs3_bind_combo.blockSignals(True)
        self._rpcs3_bind_combo.clear()
        self._rpcs3_bind_combo.addItem("Default (0.0.0.0, all interfaces)", "")
        for ip in lan_ips:
            self._rpcs3_bind_combo.addItem(ip, ip)
        bidx = self._rpcs3_bind_combo.findData(prev_bind) if prev_bind else 0
        self._rpcs3_bind_combo.setCurrentIndex(bidx if bidx >= 0 else 0)
        self._rpcs3_bind_combo.blockSignals(False)

    def _on_mode_toggled(self, checked: bool):
        # A mode switch toggles two buttons; persist on the one being checked.
        if checked:
            self._persist_connection_settings()

    def _persist_connection_settings(self):
        self._settings["rpcn_mode"]            = self.get_rpcn_mode()
        self._settings["rpcn_custom_host"]     = self.get_rpcn_custom_host()
        self._settings["gameserver_mode"]      = self.get_gameserver_mode()
        self._settings["gameserver_remote_ip"] = self.get_gameserver_remote_ip()
        save_settings(self._settings)

    def _on_iface_changed(self):
        self._settings["network_interface"] = self._iface_combo.currentData() or ""
        save_settings(self._settings)

    def _on_rpcs3_bind_changed(self):
        self._settings["rpcs3_bind_address"] = self._rpcs3_bind_combo.currentData() or ""
        save_settings(self._settings)

    def get_rpcs3_bind_address(self) -> str:
        """Return the chosen RPCS3 bind address, or '' for the RPCS3 default."""
        return self._rpcs3_bind_combo.currentData() or ""

    def _select_bind_ip(self, ip: str):
        """Select the bind-combo item for `ip` ('' == RPCS3 default) and persist it.

        setCurrentIndex only fires the save signal when the index actually
        changes, so signals are blocked and the setting is saved explicitly to
        also cover the case where the combo already sits on that item.
        """
        idx = self._rpcs3_bind_combo.findData(ip)
        if idx < 0:
            idx = 0  # fall back to the Default item if the IP is not enumerated
        self._rpcs3_bind_combo.blockSignals(True)
        self._rpcs3_bind_combo.setCurrentIndex(idx)
        self._rpcs3_bind_combo.blockSignals(False)
        self._settings["rpcs3_bind_address"] = self._rpcs3_bind_combo.currentData() or ""
        save_settings(self._settings)

    def _check_relay_bind(self):
        """One-shot WireGuard-relay bind guidance (rpcn-ports-relay.md).

        Relay players must bind RPCS3 to their 10.99.99.x tunnel IP so the game
        advertises a relay-reachable address; a relay bind left set after the
        tunnel goes down points at a dead interface and breaks all multiplayer.
        """
        if self._relay_bind_checked:
            return
        self._relay_bind_checked = True

        relay_ip = relay_bind_ip()
        saved = self._settings.get("rpcs3_bind_address", "")

        if relay_ip:
            if saved == relay_ip:
                return  # already bound to the relay tunnel IP
            if QMessageBox.question(
                    self, "WireGuard relay detected",
                    f"This machine has a WireGuard relay address ({relay_ip}).\n\n"
                    "Other relay players can reach you only when RPCS3 advertises "
                    f"this tunnel address. Set the RPCS3 bind address to {relay_ip}?",
            ) == QMessageBox.StandardButton.Yes:
                self._select_bind_ip(relay_ip)
        elif is_relay_addr(saved):
            # Stale relay bind with WireGuard off: reset to the RPCS3 default.
            self._select_bind_ip("")
            QMessageBox.information(
                self, "Relay bind cleared",
                f"WireGuard is not active, so the saved relay bind address ({saved}) "
                "was reset to the RPCS3 default.",
            )

    def _on_upnp_changed(self, checked: bool):
        self._settings["rpcs3_upnp"] = checked
        save_settings(self._settings)

    def _on_telemetry_changed(self, checked: bool):
        self._settings["enable_telemetry"] = checked
        if checked and not self._settings.get("telemetry_client_id"):
            self._settings["telemetry_client_id"] = str(uuid.uuid4())
        save_settings(self._settings)

    def get_rpcs3_upnp(self) -> bool:
        return self._upnp_check.isChecked()

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
