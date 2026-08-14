"""Launch sequence and process lifecycle for the main window.

Keeps a window reference to parent its modal dialogs and read the tabs, because
the launch flow is a chain of synchronous modal dialogs.
"""
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from app.paths import (
    _IS_WIN, APP_DIR, RPCS3_DIR, RPCN_DIR, GAMESERVER_DIR,
    RPCS3_EXE, RPCN_EXE, GAMESERVER_SCRIPT, GAMESERVER_LOG,
    PORTABLE_DIR, RPCN_YML, GAME_USRDIR,
    VERSION, RELEASE_CHANNEL, GITHUB_REPO,
    COMMUNITY_RPCN_HOST, OPERATIONS_GAME_ADDR, TELEMETRY_URL,
    FIRMWARE_INDICATOR,
    rpcs3_launch_args, rpcs3_log_path, gameserver_python,
    privileged_port_command, privileged_port_help, find_installed_game,
)
from app.settings import save_settings, parse_remote_addr
from modules import save_editor, tus_saves, processes
from modules.telemetry import TelemetryStreamer
from modules.updater import UpdateChecker
from workers.launch_worker import LaunchWorker
from workers.log_watcher import GameServerLogWatcher


class LaunchController(QObject):
    def __init__(self, window, settings: dict):
        super().__init__(window)
        self._win = window
        self._settings = settings
        self._worker: LaunchWorker | None = None
        self._gameserver  = processes.ManagedProcess("gameserver", self)
        self._rpcn_proc   = processes.ManagedProcess("rpcn", self)
        self._rpcs3_proc  = processes.ManagedProcess("rpcs3", self)

        self._restore_staged = False
        self._save_load_offer_shown = False
        self._last_penalty_check_path: str | None = None
        self._last_coop_check_path: str | None = None
        self._telemetry: TelemetryStreamer | None = None

        for proc, name in ((self._gameserver, "gameserver"),
                           (self._rpcn_proc,  "rpcn"),
                           (self._rpcs3_proc, "rpcs3")):
            proc.started.connect(lambda n=name: self._win._play_tab.set_process_status(n, True))
            proc.stopped.connect(lambda _ec, n=name: self._win._play_tab.set_process_status(n, False))

        # Refresh diagnostics after RPCS3 exits so firmware/game installs are detected.
        # Also clean up any dangling .restore sentinels and reset the staged flag.
        self._rpcs3_proc.stopped.connect(self._on_rpcs3_stopped)

        self._log_watcher = GameServerLogWatcher(GAMESERVER_LOG, self)
        self._log_watcher.save_load_error_seen.connect(self._on_save_load_error)
        self._log_watcher.start()

    def mark_restore_staged(self):
        self._restore_staged = True

    def rpcs3_is_running(self) -> bool:
        return self._rpcs3_proc.is_running()

    def shutdown(self):
        self._log_watcher.stop()
        if self._telemetry is not None:
            self._telemetry.stop()
            self._telemetry.join(timeout=15)
            self._telemetry = None
        for proc in (self._gameserver, self._rpcn_proc, self._rpcs3_proc):
            proc.stop()

    def _resolve_rpcn_host(self) -> str:
        mode = self._win._play_tab.get_rpcn_mode()
        if mode == "self_hosted":
            return "127.0.0.1"
        if mode == "custom":
            return self._win._play_tab.get_rpcn_custom_host()
        return COMMUNITY_RPCN_HOST

    def start_launch(self):
        editor = self._win._saves_tab.editor_tab
        if editor.has_pending_changes():
            reply = QMessageBox.question(
                self._win, "Unsaved save edits",
                "You edited values in the save editor but have not pressed "
                "\"Write to Files\" yet, so those changes are not staged.\n\n"
                "Write them now before launching?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Yes:
                editor._write_saves()

        issues = []
        if not FIRMWARE_INDICATOR.exists():
            issues.append("PS3 firmware is not installed.")
        if find_installed_game() is None:
            issues.append("OPERATION ETERNAL LIBERATION is not installed.")
        if issues:
            msg = "The following items are missing:\n\n" + "\n".join(f"  - {i}" for i in issues)
            msg += "\n\nYou can still open RPCS3 to complete setup, but the game will not work online until everything is ready."
            reply = QMessageBox.warning(
                self._win, "Setup incomplete", msg,
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Ok:
                return

        rpcn_mode = self._win._play_tab.get_rpcn_mode()
        gs_mode   = self._win._play_tab.get_gameserver_mode()
        self._settings["rpcn_mode"]            = rpcn_mode
        self._settings["rpcn_custom_host"]     = self._win._play_tab.get_rpcn_custom_host()
        self._settings["gameserver_mode"]      = gs_mode
        self._settings["gameserver_remote_ip"] = self._win._play_tab.get_gameserver_remote_ip()
        self._settings["rpcs3_bind_address"]   = self._win._play_tab.get_rpcs3_bind_address()
        self._settings["rpcs3_upnp"]           = self._win._play_tab.get_rpcs3_upnp()
        self._settings["game_fps"]             = self._win._play_tab.get_game_fps()
        save_settings(self._settings)

        rpcn_host = self._resolve_rpcn_host()
        if rpcn_mode == "custom" and not rpcn_host:
            QMessageBox.warning(self._win, "No RPCN server",
                                "Enter a server address in the Custom field.")
            return

        gs_remote_ip = self._win._play_tab.get_gameserver_remote_ip()
        if gs_mode == "remote":
            if not gs_remote_ip:
                QMessageBox.warning(self._win, "No game server",
                                    "Enter the remote game server address.")
                return
            try:
                parse_remote_addr(gs_remote_ip)
            except ValueError as e:
                QMessageBox.warning(self._win, "Invalid address",
                                    f"Could not parse '{gs_remote_ip}': {e}\n\n"
                                    "Expected: host  or  host:http_port:https_port")
                return

        self._save_load_offer_shown = False
        self._win._play_tab.set_launch_enabled(False)
        lan_ip_override = self._win._play_tab.get_lan_ip_override()
        bind_address    = self._win._play_tab.get_rpcs3_bind_address()
        upnp            = self._win._play_tab.get_rpcs3_upnp()
        game_fps        = self._win._play_tab.get_game_fps()
        self._worker = LaunchWorker(rpcn_host, rpcn_mode, lan_ip_override, bind_address, upnp, game_fps, self)
        self._worker.log.connect(self._on_worker_log)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.done.connect(self._on_worker_done)
        self._worker.start()

    def _on_worker_log(self, msg: str):
        # Show brief status in window title while preparing
        self._win.setWindowTitle(f"OPERATION ETERNAL LIBERATION {VERSION} - {msg}")

    def _on_worker_failed(self, msg: str):
        self._win.setWindowTitle(f"OPERATION ETERNAL LIBERATION {VERSION}")
        self._win._play_tab.set_launch_enabled(True)
        QMessageBox.critical(self._win, "Launch failed", msg)

    def _grant_port_privilege(self, gs_python: Path, bind_ip: str) -> bool:
        """Get the game server its ports 80/443 capability. Offers to grant it
        through the desktop password prompt (pkexec); falls back to a
        copy-pasteable command. Returns True once the capability is in place."""
        elevate = processes.can_elevate() and gs_python.name == "python3-gameserver"
        box = QMessageBox(self._win)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Game server ports")
        box.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        grant_btn = None
        if elevate:
            box.setText("The game server needs permission to use ports 80 and 443.\n\n"
                        "Grant it now and your system will ask for your password.")
            grant_btn = box.addButton("Grant permission", QMessageBox.ButtonRole.AcceptRole)
        else:
            box.setText(privileged_port_help())
        copy_btn = box.addButton("Copy command", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(grant_btn or copy_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked is grant_btn:
            outcome = processes.grant_port_capability(str(gs_python))
            if (outcome == "granted"
                    and not processes.needs_port_privilege(str(gs_python), bind_ip)):
                return True
            if outcome != "cancelled":
                QMessageBox.warning(
                    self._win, "Game server ports",
                    "Granting the permission did not complete. Run this in a "
                    "terminal, then launch again:\n\n" + privileged_port_command())
        elif clicked is copy_btn:
            QApplication.clipboard().setText(privileged_port_command())
        return False

    def _on_worker_done(self, swap_ip: str):
        self._win.setWindowTitle(f"OPERATION ETERNAL LIBERATION {VERSION}")
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
                QMessageBox.warning(self._win, "Invalid address",
                                    f"Could not parse remote address: {e}")
                self._win._play_tab.set_launch_enabled(True)
                return
        elif gs_mode == "operations":
            host, http_p, https_p = parse_remote_addr(OPERATIONS_GAME_ADDR)
            gs_args += [
                "--forward", host,
                "--forward-http-port",  str(http_p),
                "--forward-https-port", str(https_p),
            ]

        if not processes.is_port_open(swap_ip):
            gs_python = gameserver_python()
            if (not _IS_WIN
                    and processes.needs_port_privilege(str(gs_python), swap_ip)
                    and not self._grant_port_privilege(gs_python, swap_ip)):
                self._win._play_tab.set_launch_enabled(True)
                return
            self._launch_or_warn(
                self._gameserver, str(gs_python), gs_args,
                "Gameserver", "Could not start the game server.",
                cwd=str(GAMESERVER_DIR), new_console=True,
            )

        if rpcn_mode == "self_hosted" and not self._rpcn_proc.is_running():
            QTimer.singleShot(2000, self._start_rpcn)

        # True when RPCS3 was already up: nothing was started, so nothing failed.
        rpcs3_up = True
        if not self._rpcs3_proc.is_running():
            if not self._restore_staged:
                tus_saves.cleanup_restore_sentinels(str(PORTABLE_DIR / "tus"))
            self._restore_staged = False
            rpcs3_up = self._launch_or_warn(
                self._rpcs3_proc, str(RPCS3_EXE), rpcs3_launch_args(),
                "RPCS3", "RPCS3 did not start. Check that the emulator is present, "
                         "and on Linux that it is executable.",
                cwd=str(RPCS3_DIR),
            )

        if (rpcs3_up
                and gs_mode == "operations"
                and self._settings.get("enable_telemetry")
                and self._telemetry is None):
            self._telemetry = TelemetryStreamer(
                log_path=rpcs3_log_path(),
                url=TELEMETRY_URL,
                metadata={
                    "version":     VERSION,
                    "client_id":   self._settings.get("telemetry_client_id", ""),
                    "session_id":  str(uuid.uuid4()),
                    "app_root":    str(APP_DIR),
                    "game_usrdir": str(GAME_USRDIR),
                    "rpcs3_exe":   str(RPCS3_EXE),
                    "game_hash":   self._win._play_tab.get_game_hash(),
                    "rpcs3_hash":  "",
                },
            )
            self._telemetry.start()

        self._win._play_tab.set_launch_enabled(True)
        self._win._tss_tab.refresh()

    def _launch_or_warn(self, proc, program, args, title, message,
                        cwd=None, new_console=False) -> bool:
        """Start a process, and say so when it does not start.

        ManagedProcess.launch reports a failure by returning False and nothing else:
        it swallows the OSError, writes no log, and never connects errorOccurred.
        """
        if proc.launch(program, args, cwd=cwd, new_console=new_console):
            return True
        QMessageBox.warning(self._win, title, message)
        return False

    def _start_rpcn(self):
        """The deferred RPCN start, as a method so its result has a caller.

        A new_console launch reports the terminal starting, not the process inside
        it, so the message says what is actually known.
        """
        self._launch_or_warn(
            self._rpcn_proc, str(RPCN_EXE), [],
            "RPCN", "The RPCN console did not open.",
            cwd=str(RPCN_DIR), new_console=True,
        )

    def _on_rpcs3_stopped(self, _exit_code: int):
        if self._telemetry is not None:
            self._telemetry.stop()
            self._telemetry = None
        self._win._play_tab.refresh_setup_status()
        tus_saves.cleanup_restore_sentinels(str(PORTABLE_DIR / "tus"))
        self._restore_staged = False
        # Pick up any backups written this session before the save-state checks.
        self._win._saves_tab.editor_tab._try_auto_read()
        self.check_save_alerts()

    def check_save_alerts(self):
        # Modal dialogs, so run sequentially: penalty first, then Co-Op rate.
        self._check_penalty_rank()
        self._check_coop_rate()

    def _check_penalty_rank(self):
        editor = self._win._saves_tab.editor_tab
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
            self._win, "Penalty Rank detected",
            f"Your latest save shows a Penalty Rank of {rank}.\n\n"
            "Would you like to reset it to 0?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        confirm = QMessageBox.warning(
            self._win, "Confirm Penalty Rank reset",
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
            QMessageBox.warning(self._win, "Reset failed", msg)
            return
        self._restore_staged = True
        QMessageBox.information(
            self._win, "Done",
            "Penalty Rank reset to 0 and restore staged.\n"
            "Boot OP ETERNAL once to apply the change."
        )

    def _check_coop_rate(self):
        editor = self._win._saves_tab.editor_tab
        rate, path = editor.peek_latest_coop_rate()
        if rate is None or path is None:
            return
        floor = save_editor.COOP_MATCH_RATE_FLOOR
        if rate >= floor:
            self._last_coop_check_path = path
            return
        if path == self._last_coop_check_path:
            return
        self._last_coop_check_path = path
        reply = QMessageBox.question(
            self._win, "Co-Op Matching Rate low",
            f"Your latest save shows a Co-Op Matching Rate of {rate}, below the "
            f"{floor} needed to unlock the HARD co-op missions at First Lieutenant.\n\n"
            f"Would you like to restore it to {floor}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        confirm = QMessageBox.warning(
            self._win, "Confirm Co-Op Matching Rate change",
            f"This will write Co-Op Matching Rate = {floor} to your local save and "
            "stage it for the game to apply on next boot. The change syncs to RPCN "
            "the next time the game saves.\n\n"
            "Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        ok, msg = editor.bump_coop_from_latest()
        if not ok:
            QMessageBox.warning(self._win, "Restore failed", msg)
            return
        self._restore_staged = True
        QMessageBox.information(
            self._win, "Done",
            f"Co-Op Matching Rate set to {floor} and restore staged.\n"
            "Boot OP ETERNAL once to apply the change."
        )

    def _on_save_load_error(self):
        if self._save_load_offer_shown:
            return
        self._save_load_offer_shown = True
        reply = QMessageBox.question(
            self._win, "Save load error detected",
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
            self._win, "Confirm New Game Override",
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
            QMessageBox.warning(self._win, "Errors", "\n".join(errors))
        else:
            QMessageBox.information(
                self._win, "Done",
                f"{staged} slot(s) staged.\n"
                "Reboot OPERATION ETERNAL LIBERATION to start fresh."
            )

    def check_for_updates_startup(self):
        channel = self._settings.get("update_channel", RELEASE_CHANNEL)
        checker = UpdateChecker(self)
        checker.update_available.connect(self._on_update_available)
        checker.check(GITHUB_REPO, channel, VERSION)

    def _on_update_available(self, version: str, url: str):
        btn = QMessageBox.question(
            self._win, "Update available",
            f"Version {version} is available.\nOpen the download page?",
        )
        if btn == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(url))
