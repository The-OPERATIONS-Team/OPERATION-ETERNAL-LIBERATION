# Building

Clone with [Git](https://git-scm.com/downloads):

```
git clone <repo-url>
```

## Windows

Run `SRC\clone-git-repos.bat`, then apply the patches with `SRC\apply-patches.bat`. `SRC\reset-git-repos.bat` reverts both repos to baseline.

**RPCS3** requires [Visual Studio](https://visualstudio.microsoft.com/downloads/) with the C++ workload. Follow the upstream [BUILDING.md](https://github.com/RPCS3/rpcs3/blob/master/BUILDING.md), then copy everything from `SRC\GIT\rpcs3\bin\` into `BIN\_app\RPCS3\`.

Which version depends on how LLVM is obtained. `ci\build-all.ps1` and `ci\build-rpcs3-only.ps1` download the prebuilt LLVM libs that upstream's CI publishes, which saves about half an hour per cold build but requires the toolset those libs were built with: `LLVM_VER` in `.github\workflows\build.yml` names the version, and the `runs-on` line names the toolset. At LLVM 22.1.8 that is Visual Studio 2026. An older toolset compiles everything and then fails at the final link with unresolved `__std_*` symbols reported against the LLVM libs, which points nowhere near the cause.

Visual Studio 2022 still works if LLVM is built from source instead, as upstream's own instructions describe. The prebuilt libs are an optimisation, not a requirement.

**RPCN** requires [Rust](https://rustup.rs) (MSVC ABI), [Strawberry Perl](https://strawberryperl.com), [NASM](https://www.nasm.us/), and [protoc](https://github.com/protocolbuffers/protobuf/releases) on `PATH`:

```
cd SRC\GIT\rpcn
cargo build --release
copy target\release\rpcn.exe ..\..\BIN\_app\rpcn\rpcn.exe
```

## Linux

Run `SRC/clone-git-repos.sh`, then apply the patches with `SRC/apply-patches.sh`. `SRC/reset-git-repos.sh` reverts both repos to baseline. See `SRC/README.md` for details.

**RPCS3**: follow the upstream [BUILDING.md](https://github.com/RPCS3/rpcs3/blob/master/BUILDING.md). The release AppImage is built with rpcs3's own CI container; `.github/workflows/build.yml` has the exact invocation. Place the resulting AppImage (or a `rpcs3` binary) in `BIN/_app/RPCS3/`, and `chmod +x` it: a CI artifact arrives as a zip, which does not carry the execute bit. The launcher sets it on the way to a launch, so this only matters if you run the emulator directly.

**RPCN** requires [Rust](https://rustup.rs) and protoc:

```
cd SRC/GIT/rpcn
cargo build --release
cp target/release/rpcn ../../BIN/_app/rpcn/rpcn
```

## Packaging

**Windows**: `package.bat` requires [Inno Setup 6](https://jrsoftware.org/isdl.php) at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe` and [7-Zip](https://www.7-zip.org/download.html) at `C:\Program Files\7-Zip\7z.exe`. Produces `OP-ETERNAL-Setup-{version}.exe`, `OEL-SRC-{version}.7z`, and `OEL-DOCKER-{version}.7z`.

**Linux**: `package.sh` produces `OEL-SRC-{version}.tar.xz` and `OEL-DOCKER-{version}.tar.xz`, plus the client bundle `OP-ETERNAL-{version}-linux-x86_64.tar.xz` when an AppImage is staged in `BIN/_app/RPCS3` and `ci/provision-linux-python.sh` has provisioned the bundled Python.

All versioned from `AppVersion` in `OEL.iss`. `OEL-DOCKER` is a source bundle for Linux self-hosters; they extract it, `cd BIN`, and run `docker compose up -d --build`.
