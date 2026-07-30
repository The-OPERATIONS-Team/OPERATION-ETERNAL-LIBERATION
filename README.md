# OPERATION ETERNAL LIBERATION

A community kit for playing OPERATION ETERNAL LIBERATION online via [RPCS3](https://rpcs3.net) and a community [RPCN](https://github.com/RipleyTom/rpcn) server.

## Communities

[![OPERATION ETERNAL LIBERATION Discord](https://discord.com/api/guilds/1508671948299698248/widget.png?style=banner2)](https://discord.com/invite/KF5HjeYR)

[![Ace Combat Infinity Revival Project Discord](https://discord.com/api/guilds/1500375208144408628/widget.png?style=banner2)](https://discord.com/invite/CyvkaYTE)

## Playing

### Windows

Run the latest `OP-ETERNAL-Setup-*.exe` from the releases page. It installs the kit and creates a desktop shortcut. Open the shortcut.

### Linux

Download the latest `OP-ETERNAL-*-linux-x86_64.tar.xz` from the releases page, extract it anywhere, and run the play script:

```
tar -xJf OP-ETERNAL-*-linux-x86_64.tar.xz
cd OPERATION-ETERNAL-LIBERATION
"./Play OPERATION ETERNAL LIBERATION (Linux).sh"
```

The game server uses ports 80 and 443, so on first launch you are asked for your password to allow that.

### macOS (Apple Silicon)

Download `OP-ETERNAL-*-macos-arm64.tar.xz`, extract it, and open
**OPERATION ETERNAL LIBERATION.app**. You can also run the command entry point:

```bash
tar -xJf OP-ETERNAL-*-macos-arm64.tar.xz
cd OPERATION-ETERNAL-LIBERATION
"./Play OPERATION ETERNAL LIBERATION (macOS).command"
```

The first game launch displays the normal macOS administrator prompt because
the local game server must bind ports 80 and 443. The distributed application
is ad-hoc signed rather than notarized; if Gatekeeper quarantines the extracted
folder, right-click the app and choose **Open** once.

### All platforms

You provide:

1. PS3 firmware. When RPCS3 prompts, point it at your own `PS3UPDAT.PUP`.
2. The game at version 2.11. In RPCS3, *File > Install Packages/Raps*; install your game files.
3. The 15 TSS files. Drop them into the `TSS` folder.

Always launch the game from the launcher, not directly from RPCS3. The launcher applies the right game patches and emulator settings before starting RPCS3, and keeps the network config in sync with your current LAN IP in order to make sure that game network packet routing is correct.

The **Saves** tab includes a save editor, a save backup browser, and a "new game" override. RPCS3 writes a local copy of every cloud save, so you can roll back or restart even after the cloud copy has been overwritten.

### Updating

On Windows, run a newer installer over the existing install. On Linux or
macOS, extract a newer tarball over the existing folder. Your RPCS3 portable
data, RPCN config files, launcher settings, and `TSS` folder are preserved.

### Troubleshooting

- **"Failed to connect to Playstation Network".** Click the RPCN icon in RPCS3 to confirm you're logged in, and check that all 15 TSS files show as present in the launcher's **TSS Files** tab.
- **"Failed to connect to game server".** Make sure the mock game server is listening on the same IP as your LAN, or, if it's hosted remotely, that the remote address is reachable.
- **RPCN login fails (self-hosted).** Make sure the rpcn process is running and your firewall allows TCP 31313 and 31315.
- **Can't host or join rooms.** Right-click the game in RPCS3, open *Custom Configuration > Network*, enable **UPnP**.
- **TSS warning on launch.** Drop your 15 TSS files into the `TSS` folder.
- **"Game server ports" error (Linux).** Run the command shown in the dialog once, then launch again.
- **The macOS administrator prompt does not appear.** Launch through the app
  or the macOS `.command` file, not by running `launcher.py` from another
  environment. Check `/tmp/oel-gameserver-<uid>.log` if the server fails.
- **Campaign cutscene remains black on macOS.** Confirm the package contains
  the OEL-patched `RPCS3.app`; an unrelated or older RPCS3 build may stall in
  the CRI Mana decoder.
- **macOS logs.** RPCS3 writes `~/Library/Caches/rpcs3/RPCS3.log`; the local
  game server writes `_app/gameserver/gameserver.log`.

## Hosting your own server

`BIN/docker-compose.yml` runs the game server and RPCN together on a Linux machine. A small VPS works fine.

You need:

- A Linux box with Docker installed.
- The full project source, cloned with `git clone`.

### Build the images

From the `BIN` directory:

```
docker compose build
docker save oel-gameserver:latest oel-rpcn:latest | gzip > oel-images.tar.gz
```

If your build host's CPU architecture differs from your server's, prefix the build with `DOCKER_DEFAULT_PLATFORM=linux/amd64`.

### Copy to the server

```
scp oel-images.tar.gz docker-compose.yml user@your-vps:~/
```

### Load and start

```
mkdir -p ~/oel/_app/rpcn && cd ~/oel
mv ~/docker-compose.yml .
docker load < ~/oel-images.tar.gz
docker compose up -d
```

### Open the ports

Allow these on your VPS firewall, plus any cloud-provider firewall in front of it:

- `8000` TCP (game server HTTP)
- `8001` TCP (game server HTTPS)
- `31313` TCP (RPCN login and matchmaking)
- `31315` TCP (RPCN TSS HTTP)
- `3657` UDP (RPCN signaling)

### Add TSS files

After first start, the RPCN container creates a `tss_data/<comm_id>/` subdirectory. Copy your 15 TSS files there, then:

```
docker compose restart rpcn
```

### Connect from the launcher

On the **Play** tab:

- **RPCN Server**: pick **Custom** and enter your server's host.
- **Game Server**: pick **Remote** and enter `<host_ip>:8000:8001`.

### Logs

The game server writes its log file and rotated archives to `~/oel/logs/gameserver/` on the host. For RPCN, use `docker compose logs rpcn`.

### Updating the server

Rebuild locally, ship a new tarball, then on the server:

```
docker load < ~/oel-images.tar.gz
docker compose up -d
```

The bind-mounted `_app/rpcn/` data is preserved across updates.

## Building

See [BUILDING.md](BUILDING.md).

## Licensing

Original code by The -OPERATIONS- Team is licensed under [AGPL-3.0-or-later](LICENSE), with an additional permission to combine it with RPCS3 and convey the combined work under GPL-2.0. Upstream RPCS3 and RPCN sources, and our patches to them, follow their respective upstream licenses (GPL-2.0-only and AGPL-3.0-or-later). See [LICENSING.md](LICENSING.md) for the per-directory breakdown.

## Credits

A collaborative effort by **The -OPERATIONS- Team**:

- [Killer0byte](https://github.com/Killer0byte)
- [Optimus1200](https://github.com/Optimus1200)
- JumpSuit
- Volcano Water

## Legal Disclaimer

**OPERATION ETERNAL LIBERATION** is an independent, community-driven revival project and is **not** affiliated with, endorsed by, or otherwise connected to Bandai Namco Entertainment Inc. or any of the original rights holders of *Ace Combat Infinity*.

This project is developed strictly for **non-commercial, hobby, and preservation purposes**. It is, and will always remain, **freely available** via its official GitHub repository. Any distribution of this content in exchange for payment or other compensation is entirely unauthorized and is not endorsed by the -OPERATIONS- team. If you encounter such activity, we strongly encourage you to report it.

***

### Intellectual Property Notices

- **Ace Combat™** and **Ace Combat Infinity™** are intellectual properties of **Bandai Namco Entertainment Inc.** All rights reserved.
- All trademarks, copyrights, aircraft designations, manufacturer names, trade names, brand names, and visual imagery depicted in the original game remain the exclusive property of their respective owners and Bandai Namco Entertainment Inc.
- **PlayStation®** is a registered trademark of **Sony Interactive Entertainment Inc.**

> This project makes no claim of ownership over any of the above intellectual properties. All original assets, names, and likenesses are used solely for interoperability and non-commercial fan preservation purposes.
