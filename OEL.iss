; OPERATION ETERNAL LIBERATION - Inno Setup installer script
; Bump AppVersion for each release. Do not change AppId after first release.

#define AppName    "OPERATION ETERNAL LIBERATION"
#define AppVersion "1.0.2.4"

[Setup]
AppId={{3D7F2C1A-B8E4-4F2D-9C5E-1A2B3C4D5E6F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={sd}\Games\OPETERNAL
DisableProgramGroupPage=yes
DisableDirPage=no
OutputDir=.
OutputBaseFilename=OP-ETERNAL-Setup-{#AppVersion}
; No UAC prompt - installs entirely in the chosen folder
PrivilegesRequired=lowest
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

[Tasks]
; Remembered across updates, so an unchecked shortcut stays unchecked
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Dirs]
; User drop folder for TSS files
Name: "{app}\TSS"
; Presence of this directory enables RPCS3 portable mode
Name: "{app}\_app\RPCS3\portable"

[Files]

; Entry point
Source: "BIN\Play OPERATION ETERNAL LIBERATION (Windows).bat"; DestDir: "{app}";                Flags: ignoreversion

; User-facing quick start
Source: "BIN\READ_ME_FIRST.md";                    DestDir: "{app}";                 Flags: ignoreversion

; Launcher
Source: "BIN\_app\launcher.py";                    DestDir: "{app}\_app";            Flags: ignoreversion
Source: "BIN\_app\setup.bat";                      DestDir: "{app}\_app";            Flags: ignoreversion
Source: "BIN\_app\assets\*";                       DestDir: "{app}\_app\assets";     Flags: ignoreversion recursesubdirs

; Embeddable Python runtime (bundled so first-run needs no download).
; Provisioned on the build machine by package.bat (via setup.bat); gitignored
; like the RPCS3 binaries. setup.bat stays as a runtime fallback if absent.
Source: "BIN\_app\python\*";                       DestDir: "{app}\_app\python";     Flags: ignoreversion recursesubdirs

; Python modules
Source: "BIN\_app\modules\*.py";                   DestDir: "{app}\_app\modules";    Flags: ignoreversion

; Contributor tools (save-file diff helper for adding new save_editor fields)
Source: "BIN\_app\tools\*.py";                     DestDir: "{app}\_app\tools";      Flags: ignoreversion

; Patches
Source: "BIN\_app\patches\*";                      DestDir: "{app}\_app\patches";    Flags: ignoreversion recursesubdirs

; Game server
Source: "BIN\_app\gameserver\opeternal_listener.py"; DestDir: "{app}\_app\gameserver"; Flags: ignoreversion
Source: "BIN\_app\gameserver\gameserver.bat";      DestDir: "{app}\_app\gameserver"; Flags: ignoreversion

; RPCS3 - root files only (no recursesubdirs keeps portable\ and its user data untouched)
Source: "BIN\_app\RPCS3\*";                        DestDir: "{app}\_app\RPCS3";      Flags: ignoreversion
Source: "BIN\_app\RPCS3\qt6\*";                    DestDir: "{app}\_app\RPCS3\qt6";  Flags: ignoreversion recursesubdirs

; RPCN - executable always updated; config and certs only written on fresh install
Source: "BIN\_app\rpcn\rpcn.exe";                  DestDir: "{app}\_app\rpcn";       Flags: ignoreversion
Source: "BIN\_app\rpcn\rpcn.cfg";                  DestDir: "{app}\_app\rpcn";       Flags: onlyifdoesntexist
Source: "BIN\_app\rpcn\scoreboards.cfg";           DestDir: "{app}\_app\rpcn";       Flags: onlyifdoesntexist
Source: "BIN\_app\rpcn\server_redirs.cfg";         DestDir: "{app}\_app\rpcn";       Flags: onlyifdoesntexist
Source: "BIN\_app\rpcn\servers.cfg";               DestDir: "{app}\_app\rpcn";       Flags: onlyifdoesntexist

[Icons]
Name: "{autodesktop}\Play OPERATION ETERNAL LIBERATION";  Filename: "{app}\Play OPERATION ETERNAL LIBERATION (Windows).bat"; IconFilename: "{app}\_app\assets\oel.ico"; Tasks: desktopicon
