# OPERATION ETERNAL LIBERATION

A community kit for playing online via RPCS3 and an RPCN server.

## Quick start

On Windows, open the desktop shortcut **Play OPERATION ETERNAL LIBERATION**.

On Linux (x86_64, distros from roughly 2022 onward - RPCS3 needs glibc 2.35), run this from the install folder:

```
./Play\ OPERATION\ ETERNAL\ LIBERATION\ \(Linux\).sh
```

On Apple Silicon macOS 14.4 or newer, open
**OPERATION ETERNAL LIBERATION.app**, or run:

```bash
./Play\ OPERATION\ ETERNAL\ LIBERATION\ \(macOS\).command
```

The game server uses ports 80 and 443, so on first launch you are asked for
your password to allow that.

You provide:

1. PS3 firmware. When RPCS3 prompts, point it at your `PS3UPDAT.PUP`.
2. The game at version 2.11. In RPCS3, *File > Install Packages/Raps*, then install your game files.
3. The 15 TSS files. Drop them into the `TSS` folder next to this file.

Always launch the game from the launcher, not directly from RPCS3, so the network config matches your current LAN IP.

## Server settings

The **Play** tab has two server groups. They are independent and any combination works.

**RPCN Server** controls login and matchmaking:

- *Official*: the community RPCN at np.rpcs3.net.
- *Self-Hosted*: runs an RPCN server on your machine.
- *Custom*: any other RPCN server (enter its host).

**Game Server** controls the backend that answers the game's HTTP calls:

- *Self-Hosted*: runs on your machine. Works both for singleplayer and multiplayer (the multiplayer matchmaking and netcode is handled by RPCN).
- *Remote*: a game server hosted elsewhere. Enter the address as `host:http_port:https_port`, for example `<host_ip>:8000:8001`.

## Saves

The **Saves** tab has three things:

- A save editor for credits, fuel, tickets, and other fields.
- A backup browser. RPCS3 writes a local copy of every cloud save, so you can roll back any time.
- A "new game" override that makes the game offer a fresh start without deleting your cloud data.

## Updates

On Windows, run the newer installer over the existing install. On Linux or
macOS, extract the newer tarball over the existing folder. Either way your
RPCS3 portable data, launcher settings, and `TSS` folder are preserved.

## Troubleshooting

- **"Failed to connect to Playstation Network".** Click the RPCN icon in RPCS3 to confirm you are logged in. Check that all 15 TSS files show as present on the **TSS Files** tab.
- **"Failed to connect to game server".** If self-hosted, the game server console window should be open. If remote, check the address and that the server is reachable.
- **RPCN login fails (self-hosted).** Make sure the rpcn process is running and your firewall allows TCP 31313 and 31315.
- **Can't host or join rooms.** In RPCS3, right-click the game, open *Custom Configuration > Network*, enable **UPnP**.
- **"Game server ports" error (Linux).** Run the command shown in the dialog, or run this once from the install folder:

  ```
  sudo setcap cap_net_bind_service=+ep _app/python/bin/python3-gameserver
  ```

- **Qt platform plugin error (Linux).** Desktop distros ship the needed X11 client libraries; minimal ones may not:

  ```
  Debian/Ubuntu:  sudo apt install libxcb-cursor0 libxkbcommon-x11-0
  Fedora:         sudo dnf install xcb-util-cursor libxkbcommon-x11
  Arch:           sudo pacman -S xcb-util-cursor libxkbcommon-x11
  ```

- **Where the logs are (Linux).** RPCS3: `~/.cache/rpcs3/RPCS3.log`. Game server: `_app/gameserver/gameserver.log`.
- **Game server fails on macOS.** Approve the native administrator prompt and
  check `/tmp/oel-gameserver-<uid>.log`. The elevated server exits
  automatically when the launcher closes.
- **Campaign cutscene is black on macOS.** Use the `RPCS3.app` included in the
  OEL package. Older or unrelated builds can stall in CRI Mana video decoding.
- **Where the logs are (macOS).** RPCS3:
  `~/Library/Caches/rpcs3/RPCS3.log`. Game server:
  `_app/gameserver/gameserver.log`.

## Hosting your own server

The kit ships with a Docker setup that runs the game server and RPCN together on a Linux machine. See the Hosting section of the project README on GitHub:

https://github.com/The-OPERATIONS-Team/OPERATION-ETERNAL-LIBERATION
