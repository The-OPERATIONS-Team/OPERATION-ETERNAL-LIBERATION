"""Off-main-thread host-firewall preflight.

The Windows check shells out to PowerShell, which takes seconds to start, so it
cannot run on the GUI thread. The repair is on the worker too because it waits
on an elevation prompt the user may leave sitting.
"""
from PySide6.QtCore import QThread, Signal

from app.paths import RPCS3_EXE
from modules import netplay_firewall


class FirewallCheckWorker(QThread):
    checked = Signal(object)  # netplay_firewall.FirewallStatus

    def run(self):
        self.checked.emit(netplay_firewall.check(str(RPCS3_EXE)))


class FirewallRepairWorker(QThread):
    repaired = Signal(str, object)  # outcome, re-checked FirewallStatus

    def run(self):
        outcome = netplay_firewall.repair(str(RPCS3_EXE))
        self.repaired.emit(outcome, netplay_firewall.check(str(RPCS3_EXE)))
