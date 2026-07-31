# Licensing

This repository contains original code authored by The -OPERATIONS- Team alongside patches and build glue that interact with upstream projects under their own licenses. The table below maps each subtree to its governing license.

| Path | License | Notes |
|---|---|---|
| `BIN/_app/**` (launcher, gameserver, modules, patches, assets) | AGPL-3.0-or-later, with RPCS3 compatibility exception | Original code. See [LICENSE](LICENSE). |
| `BIN/Play OPERATION ETERNAL LIBERATION.*` | AGPL-3.0-or-later, with RPCS3 compatibility exception | Original code. |
| `BIN/docker/**`, `BIN/docker-compose.yml` | AGPL-3.0-or-later, with RPCS3 compatibility exception | Original code. |
| `OEL.iss`, `package.bat`, `package.sh`, `package-macos.sh`, `packaging/**` | AGPL-3.0-or-later, with RPCS3 compatibility exception | Original code. |
| `ci/**`, `WORK/**` | AGPL-3.0-or-later, with RPCS3 compatibility exception | Original code. |
| `SRC/clone-git-repos.*`, `SRC/apply-patches.*`, `SRC/reset-git-repos.*`, `SRC/pinned-commits.env`, `SRC/README.md`, `SRC/EXTERN_PATCHES.md` | AGPL-3.0-or-later, with RPCS3 compatibility exception | Original code and documentation. |
| `SRC/PATCH/RPCS3/*.patch` | GPL-2.0-only | Derivative of RPCS3 sources. Matches the upstream RPCS3 license. |
| `SRC/PATCH/RPCN/*.patch` | AGPL-3.0-or-later | Derivative of RPCN sources. Matches the upstream RPCN license. |
| `SRC/GIT/rpcs3/` (cloned by `clone-git-repos` scripts) | GPL-2.0-only | Upstream [RPCS3](https://github.com/RPCS3/rpcs3). See that repository's `LICENSE`. |
| `SRC/GIT/rpcn/` (cloned by `clone-git-repos` scripts) | AGPL-3.0-or-later | Upstream [RPCN](https://github.com/RipleyTom/rpcn). See that repository's `LICENSE`. |
| `README.md`, `LICENSE`, `LICENSING.md` | AGPL-3.0-or-later, with RPCS3 compatibility exception | Documentation. |

## RPCS3 compatibility exception

The original code in this repository is licensed AGPL-3.0-or-later, with an additional permission (granted under AGPL-3.0 section 7) allowing it to be combined with RPCS3 and conveyed under GPL-2.0. The full text of that permission is in [LICENSE](LICENSE).

This permission exists because RPCS3 is licensed GPL-2.0-only, which is not directly combinable with AGPL-3.0. The exception applies only to combinations involving RPCS3; the standalone program remains AGPL-3.0-or-later.

## Distributed binary bundles

The Windows installer produced by `package.bat` bundles:

- The launcher and game server (AGPL-3.0-or-later, with the RPCS3 exception).
- RPCS3 (GPL-2.0-only) and our patches to it (GPL-2.0-only).
- RPCN (AGPL-3.0-or-later) and our patches to it (AGPL-3.0-or-later).
- An embeddable CPython 3.12 runtime (PSF License) and PySide6 (LGPL-3.0) installed at first run.

Each component remains under its original license inside the bundle. Mere aggregation in the same installer does not relicense any of them.
