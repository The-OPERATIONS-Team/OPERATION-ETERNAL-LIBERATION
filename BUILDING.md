# Building

Clone with [Git](https://git-scm.com/downloads):

```
git clone <repo-url>
```

## Windows

Run `SRC\clone-git-repos.bat`, then apply the patches with `SRC\apply-patches.bat`. `SRC\reset-git-repos.bat` reverts both repos to baseline.

**RPCS3** requires [Visual Studio 2022](https://visualstudio.microsoft.com/downloads/) with the C++ workload. Follow the upstream [BUILDING.md](https://github.com/RPCS3/rpcs3/blob/master/BUILDING.md), then copy everything from `SRC\GIT\rpcs3\bin\` into `BIN\_app\RPCS3\`.

**RPCN** requires [Rust](https://rustup.rs) (MSVC ABI), [Strawberry Perl](https://strawberryperl.com), [NASM](https://www.nasm.us/), and [protoc](https://github.com/protocolbuffers/protobuf/releases) on `PATH`:

```
cd SRC\GIT\rpcn
cargo build --release
copy target\release\rpcn.exe ..\..\BIN\_app\rpcn\rpcn.exe
```

## Linux

Run `SRC/clone-git-repos.sh`, then apply the patches with `SRC/apply-patches.sh`. `SRC/reset-git-repos.sh` reverts both repos to baseline. See `SRC/README.md` for details.

**RPCS3**: follow the upstream [BUILDING.md](https://github.com/RPCS3/rpcs3/blob/master/BUILDING.md). The release AppImage is built with rpcs3's own CI container; `.github/workflows/build.yml` has the exact invocation. Place the resulting AppImage (or a `rpcs3` binary) in `BIN/_app/RPCS3/`.

**RPCN** requires [Rust](https://rustup.rs) and protoc:

```
cd SRC/GIT/rpcn
cargo build --release
cp target/release/rpcn ../../BIN/_app/rpcn/rpcn
```

## macOS (Apple Silicon)

The macOS client is built natively for arm64 and requires macOS 14.4 or newer,
Xcode Command Line Tools, Homebrew, Rust, and approximately 80 GiB of free
space for a clean source build:

```bash
xcode-select --install
brew install cmake ninja ccache llvm@21 qt sdl3 opencv@4 \
  molten-vk vulkan-headers vulkan-loader protobuf rust p7zip gcc
```

The local build helper reads the pinned commits and ordered OEL patch series,
including the Apple Silicon RPCS3 revision tested with CRI Mana campaign
playback, builds RPCS3 and RPCN, and stages both under `BIN/_app`:

```bash
./ci/build-macos.sh
```

It uses RPCS3's macOS deployment tooling to bundle Qt, MoltenVK, and non-system
libraries into `RPCS3.app`; do not substitute an app from an existing user
installation. Homebrew `protobuf` and `fmt` have conflicted with RPCS3's
bundled dependencies in some configurations. The pinned upstream build flow
temporarily unlinks conflicting formulae; the helper records and restores
their previous Homebrew link state afterward.

Provision the self-contained arm64 Python runtime and build the complete
client archive:

```bash
./ci/provision-macos-python.sh
./package-macos.sh
```

`package-macos.sh` verifies arm64 slices, app signatures, MoltenVK layout,
symlink containment, and the absence of Homebrew/build-tree load paths before
creating `OP-ETERNAL-{version}-macos-arm64.tar.xz`.

The produced apps are ad-hoc signed. Developer ID signing and Apple
notarization require maintainer-owned credentials and are outside the local
build.

## Packaging

**Windows**: `package.bat` requires [Inno Setup 6](https://jrsoftware.org/isdl.php) at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe` and [7-Zip](https://www.7-zip.org/download.html) at `C:\Program Files\7-Zip\7z.exe`. Produces `OP-ETERNAL-Setup-{version}.exe`, `OEL-SRC-{version}.7z`, and `OEL-DOCKER-{version}.7z`.

**Linux**: `package.sh` produces `OEL-SRC-{version}.tar.xz` and `OEL-DOCKER-{version}.tar.xz`, plus the client bundle `OP-ETERNAL-{version}-linux-x86_64.tar.xz` when an AppImage is staged in `BIN/_app/RPCS3` and `ci/provision-linux-python.sh` has provisioned the bundled Python.

**macOS**: `package-macos.sh` produces
`OP-ETERNAL-{version}-macos-arm64.tar.xz` and its SHA-256 file after
`ci/build-macos.sh` has staged RPCS3/RPCN and
`ci/provision-macos-python.sh` has staged Python.

All versioned from `AppVersion` in `OEL.iss`. `OEL-DOCKER` is a source bundle for Linux self-hosters; they extract it, `cd BIN`, and run `docker compose up -d --build`.
