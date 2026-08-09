"""Netplay inbound-firewall preflight.

RPCS3 has to accept unsolicited inbound UDP to host a room and be joined. A host
firewall that drops that inbound leaves a player able to join others but unable
to be joined, which looks like "nobody can find my room."

The Windows trap: dismissing the "Windows Security Alert" popup writes an inbound
*Block* rule for rpcs3, and a Block rule overrides any Allow, so a later allow
rule does nothing. This module detects that block, plus the plain "no allow rule"
case, and can repair both by deleting rpcs3's inbound rules and adding a single
allow for all profiles.

Linux has no per-app popup: ufw and firewalld are default-deny on inbound only
when active, so the check is "is a firewall active and is the netplay port open."

Pure stdlib and safe to import and call headless on any OS. check() reads only what
an ordinary user can, and reports "unknown" rather than guessing when it cannot read
at all; repair() raises a desktop password prompt (UAC on Windows, polkit on Linux)
and returns "granted" / "cancelled" / "failed" / "unsupported".
"""
import shutil
import subprocess
import sys
from dataclasses import dataclass

from modules import elevation

P2P_PORT = 3658  # RPCS3 nt_p2p_port default

# Firewall rules, read from the registry rather than the NetSecurity cmdlets.
# Get-NetFirewallRule and Get-NetFirewallApplicationFilter both need elevation and
# fail with access denied for an ordinary user, which is who runs this. The registry
# copy is world readable, and its rules are pipe-delimited with English keys whatever
# the system language, where netsh prints localised field names.
# The marker separates "read it, found nothing" from "could not read it", which is
# the distinction the whole check turns on.
_FW_KEY = (r"HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess"
           r"\Parameters\FirewallPolicy\FirewallRules")
_FW_OK = "OEL-FW-OK"
_PS_FIREWALL_RULES = (
    "$ErrorActionPreference='Stop'; "
    "try { "
    f"  $p = Get-ItemProperty -Path '{_FW_KEY}'; "
    f"  Write-Output '{_FW_OK}'; "
    "  $p.PSObject.Properties | Where-Object {{ $_.Value -is [string] }} | "
    "    ForEach-Object {{ $_.Value }} "
    "} catch {{ }}"
).replace("{{", "{").replace("}}", "}")


def _parse_rule(raw: str) -> dict:
    """One pipe-delimited registry rule into its fields.

    Profile repeats once per profile the rule covers, and a rule with none covers
    all of them, which is what Windows shows as Any.
    """
    fields: dict = {}
    profiles: list[str] = []
    for token in raw.split("|"):
        key, sep, value = token.partition("=")
        if not sep:
            continue
        if key == "Profile":
            profiles.append(value)
        else:
            fields[key] = value
    fields["Profiles"] = profiles or ["Any"]
    return fields


def _same_program(app: str, exe: str) -> bool:
    """Whether a rule's program is this executable.

    Windows matches the rule to the exact path, so a rule for another copy of
    rpcs3.exe does not admit this one however similar the name.
    """
    return app.replace("/", "\\").casefold() == exe.replace("/", "\\").casefold()


@dataclass
class FirewallStatus:
    """Result of a preflight check.

    state is one of:
      ok            inbound netplay is allowed
      blocked       an enabled Block rule is dropping it (the dismissed-popup trap)
      missing_allow no Block, but no allow covering the profiles a peer arrives on
      unknown       could not determine (e.g. ufw active but unreadable unprivileged)
      unsupported   no preflight for this OS
    """
    state: str
    summary: str
    detail: str = ""
    fixable: bool = False

    @property
    def is_problem(self) -> bool:
        """True only for states worth prompting the user about."""
        return self.state in ("blocked", "missing_allow")


def check(rpcs3_exe: str, port: int = P2P_PORT) -> FirewallStatus:
    """Report whether the host firewall will admit RPCS3's inbound netplay."""
    if sys.platform == "win32":
        return _check_windows(rpcs3_exe)
    if sys.platform.startswith("linux"):
        return _check_linux(port)
    return FirewallStatus("unsupported", "Firewall preflight is not available on this OS.")


def repair(rpcs3_exe: str, port: int = P2P_PORT) -> str:
    """Fix the firewall for RPCS3 netplay behind a desktop privilege prompt.

    Returns "granted", "cancelled" (prompt dismissed), "failed", or
    "unsupported". Re-run check() afterwards to confirm.
    """
    if sys.platform == "win32":
        return _repair_windows(rpcs3_exe)
    if sys.platform.startswith("linux"):
        return _repair_linux(port)
    return "unsupported"


# --- shared helpers ---------------------------------------------------------

def _run(argv: list[str], hide_window: bool = False) -> str | None:
    """Run argv, return stdout, or None on any failure. Never raises."""
    kwargs = {}
    if hide_window and sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # no console flash from the GUI
        kwargs["startupinfo"] = si
    try:
        res = subprocess.run(argv, capture_output=True, text=True, timeout=20, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return None
    # A command that failed has no output to report. Returning its empty stdout would
    # make "the query was refused" read as "there is nothing there", which is how an
    # unreadable firewall came out as an unconfigured one.
    if res.returncode != 0:
        return None
    return res.stdout


# --- Windows ----------------------------------------------------------------

def _check_windows(rpcs3_exe: str) -> FirewallStatus:
    out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_FIREWALL_RULES],
               hide_window=True)
    if out is None or _FW_OK not in out:
        return FirewallStatus("unknown", "Could not read the Windows Firewall rules.")

    rules = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        fields = _parse_rule(line)
        if (fields.get("Dir") == "In"
                and fields.get("Active", "").upper() == "TRUE"
                and _same_program(fields.get("App", ""), rpcs3_exe)):
            rules.append(fields)

    def covers(fields, want):
        return any(p in ("Any", want) for p in fields["Profiles"])

    if any(r.get("Action") == "Block" and (covers(r, "Private") or covers(r, "Public"))
           for r in rules):
        return FirewallStatus(
            "blocked",
            "Windows Firewall is blocking RPCS3 netplay.",
            "A Block rule (from dismissing the firewall popup) overrides any Allow, "
            "so others cannot join your games. It must be removed.",
            fixable=True,
        )

    allowed = [r for r in rules if r.get("Action") == "Allow"]
    if not (any(covers(r, "Private") for r in allowed) and any(covers(r, "Public") for r in allowed)):
        return FirewallStatus(
            "missing_allow",
            "RPCS3 is not allowed through Windows Firewall for netplay.",
            "Without an inbound allow on both Private and Public networks, others cannot join you.",
            fixable=True,
        )
    return FirewallStatus("ok", "RPCS3 inbound netplay is allowed.")


def _repair_windows(rpcs3_exe: str) -> str:
    # Adding the allow is the whole repair unless a Block rule is in the way, and a
    # Block can only be cleared by deleting the program's inbound rules wholesale
    # since netsh cannot filter a delete by action. Each command is its own elevation
    # prompt, so the delete is only asked for when there is something to delete.
    # The rule is on the program, not the port: it survives the player changing
    # nt_p2p_port, and it opens nothing for anything else.
    netsh = elevation.system32("netsh.exe")
    allow = [netsh, "advfirewall", "firewall", "add", "rule",
             "name=OP ETERNAL - RPCS3 netplay (in)", "dir=in", "action=allow",
             f"program={rpcs3_exe}", "enable=yes", "profile=any"]
    if _check_windows(rpcs3_exe).state != "blocked":
        return elevation.run([allow])
    return elevation.run([
        [netsh, "advfirewall", "firewall", "delete", "rule",
         "name=all", f"program={rpcs3_exe}", "dir=in"],
        allow,
    ])


# --- Linux ------------------------------------------------------------------

def _firewalld_running() -> bool:
    return (_run(["firewall-cmd", "--state"]) or "").strip() == "running"


def _check_linux(port: int) -> FirewallStatus:
    # firewalld (Fedora and others): queryable without privilege.
    if shutil.which("firewall-cmd") and _firewalld_running():
        answer = _run(["firewall-cmd", f"--query-port={port}/udp"])
        if answer is not None and answer.strip() == "yes":
            return FirewallStatus("ok", f"firewalld allows udp/{port} (RPCS3 netplay).")
        return FirewallStatus(
            "missing_allow",
            f"firewalld is active and udp/{port} is not open.",
            "Others may be unable to join your hosted games.",
            fixable=True,
        )
    # ufw (Debian/Ubuntu): reading rules needs root, so we can only see that it
    # is active, never whether the port is open. Left unfixable so an unreadable
    # firewall stays silent instead of nagging a setup that already works.
    if shutil.which("ufw") and (_run(["systemctl", "is-active", "ufw"]) or "").strip() == "active":
        return FirewallStatus(
            "unknown",
            f"ufw is active; udp/{port} cannot be verified without privilege.",
            f"If people cannot join you, allow udp/{port} inbound.",
        )
    return FirewallStatus("ok", "No active host firewall detected.")


def _repair_linux(port: int) -> str:
    if shutil.which("firewall-cmd") and _firewalld_running():
        firewall_cmd = shutil.which("firewall-cmd")
        commands = [[firewall_cmd, f"--add-port={port}/udp", "--permanent"],
                    [firewall_cmd, "--reload"]]
    elif shutil.which("ufw"):
        commands = [[shutil.which("ufw"), "allow", f"{port}/udp"]]
    else:
        return "unsupported"
    return elevation.run(commands)
