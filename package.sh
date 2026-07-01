#!/usr/bin/env bash
# Build the source and Docker release archives on Linux.
# The Windows installer (.exe) is built by package.bat under InnoSetup on
# Windows; that step is skipped here.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

# Pull AppVersion out of OEL.iss (same source of truth as package.bat).
VERSION="$(awk -F'"' '/^#define AppVersion/ {print $2; exit}' "$ROOT/OEL.iss")"
if [ -z "$VERSION" ]; then
    echo "ERROR: could not parse AppVersion from $ROOT/OEL.iss" >&2
    exit 1
fi

echo "============================================================"
echo " ACI-RPCS3 - Package builder (Linux)"
echo "============================================================"
echo "Output: $ROOT  (version $VERSION)"
echo

# 1. SRC archive
echo "[1/3] Packaging SRC..."
SRC_TAR="$ROOT/OEL-SRC-$VERSION.tar.xz"
rm -f "$SRC_TAR"
tar -C "$ROOT" -cJf "$SRC_TAR" \
    SRC/README.md \
    SRC/PATCH \
    SRC/apply-patches.bat \
    SRC/apply-patches.sh \
    SRC/clone-git-repos.bat \
    SRC/clone-git-repos.sh \
    SRC/reset-git-repos.bat \
    SRC/reset-git-repos.sh \
    SRC/pinned-commits.env
echo "Done."
echo

# 2. Docker source bundle
echo "[2/3] Bundling Docker source..."
DSTAGE="$(mktemp -d)"
trap 'rm -rf "$DSTAGE"' EXIT
BUNDLE="$DSTAGE/OEL-DOCKER-$VERSION"
mkdir -p \
    "$BUNDLE/BIN/docker/gameserver" \
    "$BUNDLE/BIN/docker/rpcn" \
    "$BUNDLE/BIN/_app/gameserver" \
    "$BUNDLE/BIN/_app/assets" \
    "$BUNDLE/SRC/PATCH/RPCN"
cp "$ROOT/BIN/docker-compose.yml"                       "$BUNDLE/BIN/"
cp "$ROOT/BIN/docker/gameserver/Dockerfile"             "$BUNDLE/BIN/docker/gameserver/"
cp "$ROOT/BIN/docker/rpcn/Dockerfile"                   "$BUNDLE/BIN/docker/rpcn/"
cp "$ROOT/BIN/docker/rpcn/entrypoint.sh"                "$BUNDLE/BIN/docker/rpcn/"
cp "$ROOT/BIN/_app/gameserver/opeternal_listener.py"    "$BUNDLE/BIN/_app/gameserver/"
cp "$ROOT/BIN/_app/assets/ascii.txt"                    "$BUNDLE/BIN/_app/assets/"
cp "$ROOT/SRC/PATCH/RPCN/tss-server.patch"              "$BUNDLE/SRC/PATCH/RPCN/"
cp "$ROOT/BIN/docker/PACKAGE-README.md"                 "$BUNDLE/README.md"

DOCKER_TAR="$ROOT/OEL-DOCKER-$VERSION.tar.xz"
rm -f "$DOCKER_TAR"
tar -C "$DSTAGE" -cJf "$DOCKER_TAR" "OEL-DOCKER-$VERSION"
echo "Done."
echo

# 3. Linux client bundle (Linux counterpart of the Inno Setup installer).
# Built only when the patched RPCS3 AppImage has been staged into
# BIN/_app/RPCS3 (done by CI; see .github/workflows/build.yml).
echo "[3/3] Bundling Linux client..."
APPIMAGE="$(find "$ROOT/BIN/_app/RPCS3" -maxdepth 1 -name '*.AppImage' -print -quit 2>/dev/null || true)"
CLIENT_TAR="$ROOT/OP-ETERNAL-$VERSION-linux-x86_64.tar.xz"
if [ -z "$APPIMAGE" ]; then
    echo "No AppImage in BIN/_app/RPCS3 - skipping the client bundle."
else
    for req in "$ROOT/BIN/_app/rpcn/rpcn" "$ROOT/BIN/_app/python/bin/python3"; do
        if [ ! -e "$req" ]; then
            echo "ERROR: missing $req (stage rpcn and run ci/provision-linux-python.sh first)" >&2
            exit 1
        fi
    done

    CSTAGE="$(mktemp -d)"
    CBUNDLE="$CSTAGE/OPERATION-ETERNAL-LIBERATION"
    mkdir -p \
        "$CBUNDLE/TSS" \
        "$CBUNDLE/_app/gameserver" \
        "$CBUNDLE/_app/rpcn" \
        "$CBUNDLE/_app/RPCS3/portable"

    # Entry point + user-facing readme
    cp "$ROOT/BIN/Play OPERATION ETERNAL LIBERATION (Linux).sh" "$CBUNDLE/"
    cp "$ROOT/BIN/READ_ME_FIRST.md"                             "$CBUNDLE/"

    # Launcher
    cp "$ROOT/BIN/_app/launcher.py" "$ROOT/BIN/_app/setup.sh"   "$CBUNDLE/_app/"
    cp -r "$ROOT/BIN/_app/assets"                               "$CBUNDLE/_app/assets"
    mkdir -p "$CBUNDLE/_app/modules" "$CBUNDLE/_app/tools" "$CBUNDLE/_app/data"
    cp "$ROOT/BIN/_app/modules/"*.py                            "$CBUNDLE/_app/modules/"
    cp "$ROOT/BIN/_app/tools/"*.py                              "$CBUNDLE/_app/tools/"
    # Launcher packages (launcher.py imports these)
    for pkg in app views viewmodels workers; do
        mkdir -p "$CBUNDLE/_app/$pkg"
        cp "$ROOT/BIN/_app/$pkg/"*.py                           "$CBUNDLE/_app/$pkg/"
    done
    # Game-file verification manifest
    cp "$ROOT/BIN/_app/data/game_manifest.json"                "$CBUNDLE/_app/data/"
    cp -r "$ROOT/BIN/_app/patches"                              "$CBUNDLE/_app/patches"

    # Game server
    cp "$ROOT/BIN/_app/gameserver/opeternal_listener.py" \
       "$ROOT/BIN/_app/gameserver/gameserver.sh"                "$CBUNDLE/_app/gameserver/"

    # Bundled Python runtime (symlinks preserved by cp -a and tar)
    cp -a "$ROOT/BIN/_app/python"                               "$CBUNDLE/_app/python"

    # RPCS3: the patched AppImage; portable/ enables RPCS3 portable mode and
    # carries the staged GuiConfigs/Icons when present
    cp "$APPIMAGE"                                              "$CBUNDLE/_app/RPCS3/"
    for sub in GuiConfigs Icons; do
        if [ -d "$ROOT/BIN/_app/RPCS3/portable/$sub" ]; then
            cp -r "$ROOT/BIN/_app/RPCS3/portable/$sub"          "$CBUNDLE/_app/RPCS3/portable/$sub"
        fi
    done

    # RPCN
    cp "$ROOT/BIN/_app/rpcn/rpcn" \
       "$ROOT/BIN/_app/rpcn/rpcn.cfg" \
       "$ROOT/BIN/_app/rpcn/scoreboards.cfg" \
       "$ROOT/BIN/_app/rpcn/server_redirs.cfg" \
       "$ROOT/BIN/_app/rpcn/servers.cfg"                        "$CBUNDLE/_app/rpcn/"

    chmod +x \
        "$CBUNDLE/Play OPERATION ETERNAL LIBERATION (Linux).sh" \
        "$CBUNDLE/_app/setup.sh" \
        "$CBUNDLE/_app/gameserver/gameserver.sh" \
        "$CBUNDLE/_app/RPCS3/"*.AppImage \
        "$CBUNDLE/_app/rpcn/rpcn"

    rm -f "$CLIENT_TAR"
    # ~700 MB of staged binaries; multi-threaded xz keeps this reasonable.
    XZ_OPT="-T0" tar -C "$CSTAGE" -cJf "$CLIENT_TAR" "OPERATION-ETERNAL-LIBERATION"
    rm -rf "$CSTAGE"
    echo "Done."
fi
echo

cat <<EOF
============================================================
 Packaging complete:
   OEL-SRC-$VERSION.tar.xz       - source and patches (for DIY builders)
   OEL-DOCKER-$VERSION.tar.xz    - Docker source bundle (for Linux self-hosting)
   OP-ETERNAL-$VERSION-linux-x86_64.tar.xz - Linux client (when staged)

 The Windows installer (OP-ETERNAL-Setup-$VERSION.exe) is produced
 only by package.bat on Windows with InnoSetup.

 TSS files are not bundled. Users must obtain them separately.
============================================================
EOF
