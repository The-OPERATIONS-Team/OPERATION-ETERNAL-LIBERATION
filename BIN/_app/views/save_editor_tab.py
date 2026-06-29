"""Save Editor sub-tab."""
import glob
import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton,
    QFormLayout, QSpinBox, QFrame, QScrollArea, QFileDialog, QMessageBox,
)

from app.paths import PORTABLE_DIR, APP_DIR
from app.settings import load_settings, save_settings
from modules import games, save_editor


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
        # Snapshot of spin values as last read from / written to disk. Anything
        # differing from this is an unwritten edit (see has_pending_changes).
        self._baseline: dict[str, int] = {}
        # Optional callable returning True while the game/RPCS3 is running, so
        # writes can warn the user to close it first. Set by the launcher.
        self._game_running_check = None
        self._build_ui()
        self._try_auto_read()

    def set_game_running_check(self, fn):
        self._game_running_check = fn

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

        # Co-Op Matching Rate quick action (always visible), with a button to
        # raise a low rate back to the floor.
        coop_row = QHBoxLayout()
        self._coop_label = QLabel("Co-Op Matching Rate: --")
        self._bump_coop_btn = QPushButton(
            f"Restore to {save_editor.COOP_MATCH_RATE_FLOOR}")
        self._bump_coop_btn.setEnabled(False)
        self._bump_coop_btn.clicked.connect(self._bump_coop_rate)
        coop_row.addWidget(self._coop_label, 1)
        coop_row.addWidget(self._bump_coop_btn)
        root.addLayout(coop_row)

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
        npwr_root = PORTABLE_DIR / "tus" / games.ACTIVE.comm_id
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
        npwr_root = PORTABLE_DIR / "tus" / games.ACTIVE.comm_id
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
        self._refresh_coop_label()
        self._capture_baseline()
        return errors

    def _capture_baseline(self):
        """Mark the current spin values as matching what is on disk."""
        self._baseline = {arg: spin.value() for arg, spin in self._spins.items()}

    def has_pending_changes(self) -> bool:
        """True if a save field was edited but not yet written to the files."""
        if not (self._slot2 or self._slot3 or self._slot4):
            return False
        return any(spin.value() != self._baseline.get(arg, spin.value())
                   for arg, spin in self._spins.items())

    def _refresh_penalty_label(self):
        if self._slot4 is None:
            self._penalty_label.setText("Penalty Rank: --")
        else:
            val = self._slot4.read_all().get("penalty-rank", 0)
            self._penalty_label.setText(f"Penalty Rank: {val}")

    def _refresh_coop_label(self):
        if self._slot3 is None:
            self._coop_label.setText("Co-Op Matching Rate: --")
            self._bump_coop_btn.setEnabled(False)
            return
        val = self._slot3.read_coop_match_rate()
        self._coop_label.setText(f"Co-Op Matching Rate: {val}")
        # Only enabled below the floor; writing the floor to a higher rate would lower it.
        self._bump_coop_btn.setEnabled(val < save_editor.COOP_MATCH_RATE_FLOOR)

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
        if self._game_running_check is not None and self._game_running_check():
            reply = QMessageBox.warning(
                self, "Game is running",
                "OP ETERNAL is still running.\n\n"
                "It's recommended to close the game before writing saves, "
                "otherwise the game may overwrite your changes when it next "
                "saves or exits.\n\n"
                "Write anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
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
            self._capture_baseline()
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
            # The file now matches this spin; don't flag it as a pending edit.
            self._baseline["penalty-rank"] = 0
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

    def _bump_coop_rate(self):
        if self._slot3 is None:
            QMessageBox.warning(self, "Not loaded", "Slot 3 has not been read yet.")
            return
        ok, msg = self._apply_coop_bump()
        if not ok:
            QMessageBox.critical(self, "Restore failed", msg)
            return
        floor = save_editor.COOP_MATCH_RATE_FLOOR
        QMessageBox.information(
            self, "Co-Op Matching Rate restored",
            f"Co-Op Matching Rate set to {floor} and restore staged.\n\n"
            "Boot OP ETERNAL once to apply the change."
        )

    def _apply_coop_bump(self) -> tuple[bool, str]:
        if self._slot3 is None:
            return False, "Slot 3 has not been read yet."
        try:
            self._slot3.write_coop_match_rate(save_editor.COOP_MATCH_RATE_FLOOR)
            self._slot3.save()
            self._stage_restore(self._slot3)
        except Exception as e:
            return False, str(e)
        self._refresh_coop_label()
        self.restore_staged.emit()
        return True, ""

    def peek_latest_coop_rate(self) -> tuple[int | None, str | None]:
        """Return (coop_match_rate, backup_path) for the newest slot 3 backup, else (None, None)."""
        if not self._save_dir:
            return None, None
        backups_dir = os.path.join(self._save_dir, "backups")
        candidates = sorted(glob.glob(os.path.join(backups_dir, "*_00000000000000000003.tdt")))
        if not candidates:
            return None, None
        latest = candidates[-1]
        try:
            slot = save_editor.SaveSlot(3, latest)
            return slot.read_coop_match_rate(), latest
        except Exception:
            return None, None

    def bump_coop_from_latest(self) -> tuple[bool, str]:
        """Reload slots from the latest backups, raise the Co-Op rate to the floor, refresh the UI."""
        if not self._save_dir:
            return False, "No save folder."
        self._load_slots()
        return self._apply_coop_bump()
