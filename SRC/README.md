# Building from source

Clone the two repos at the correct commits, then apply the patches.

Windows commands below use the `.bat` scripts; on Linux and macOS use the
`.sh` scripts the same way.

If you downloaded the source archive as `OEL-SRC-*.7z` (built on Windows) and
are working on Linux or macOS, convert line endings and make the scripts
executable first:

```
dos2unix *.sh pinned-commits.env
chmod +x *.sh
```

The `OEL-SRC-*.tar.xz` archive is built on Linux and needs neither step.

## 1. Clone

```
clone-git-repos.bat
```

To revert to baseline at any point: `reset-git-repos.bat`.

## 2. Apply patches

```
apply-patches.bat
```

## 3. Build

### Windows

**RPCS3** - see `GIT\rpcs3\BUILDING.md` (Visual Studio 2022). Copy `GIT\rpcs3\bin\` output to `BIN\_app\RPCS3\`.

**RPCN** - requires Rust (MSVC ABI), Strawberry Perl, NASM, and protoc on PATH.

```
cd GIT\rpcn
cargo build --release
copy target\release\rpcn.exe ..\..\BIN\_app\rpcn\rpcn.exe
```

### Linux

**RPCS3** - see `GIT/rpcs3/BUILDING.md`. The release AppImage is produced with rpcs3's own CI container; `.github/workflows/build.yml` in the repo root has the exact `docker run` invocation. Place the AppImage (or the `rpcs3` binary) in `BIN/_app/RPCS3/`.

**RPCN** - requires Rust and protoc.

```
cd GIT/rpcn
cargo build --release
cp target/release/rpcn ../../BIN/_app/rpcn/rpcn
```

### macOS (Apple Silicon)

From the repository root, `ci/build-macos.sh` performs these clone and patch
steps when needed, selects the Apple Silicon RPCS3 revision from
`pinned-commits.env`, builds both pinned projects, deploys the self-contained
`RPCS3.app`, and stages the arm64 RPCN executable:

```bash
./ci/build-macos.sh
./ci/provision-macos-python.sh
./package-macos.sh
```

See the root `BUILDING.md` for prerequisites and bundle verification details.
