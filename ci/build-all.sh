#!/usr/bin/env bash
# Linux build pipeline. Mirrors ci/build-all.ps1 for the Windows VM.
# Resets submodules to pinned commits and reapplies patches every run for
# reproducible builds.
# Prereqs: ci/install-prereqs.sh + ci/install-qt.sh already ran.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Pinned commits - shared source of truth with clone-git-repos.sh.
PINNED_ENV="$REPO_ROOT/SRC/pinned-commits.env"
if [ ! -f "$PINNED_ENV" ]; then
    echo "ERROR: Missing $PINNED_ENV" >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$PINNED_ENV"
# A CRLF checkout of the pin file glues a carriage return onto every value, which
# then rides along on the clone URL. build-all-linux.sh strips it at the read.
RPCS3_URL="${RPCS3_URL%$'\r'}";  RPCS3_COMMIT="${RPCS3_COMMIT%$'\r'}"
RPCN_URL="${RPCN_URL%$'\r'}";    RPCN_COMMIT="${RPCN_COMMIT%$'\r'}"

# Deploy destinations inside the repo. Preserve subdirs (portable/ for RPCS3,
# tss_data/ for RPCN) which hold user/runtime state.
RPCS3_DEPLOY="BIN/_app/RPCS3"
RPCN_DEPLOY="BIN/_app/rpcn"

# Source the Rust env if rustup installed it under $HOME.
[ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"

# Pick up QTDIR from install-qt.sh's recommendation if the caller exported it.
if [ -n "${QTDIR:-}" ]; then
    export PATH="$QTDIR/bin:$PATH"
fi

step() { echo; echo "=== $1 ==="; }

sync_submodule() {
    local path="$1" url="$2" commit="$3"
    if [ -d "$path/.git" ]; then
        ( cd "$path" \
            && git reset --hard HEAD \
            && git clean -ffdx \
            && git fetch origin \
            && git checkout "$commit" \
            && git submodule update --init --recursive --depth 1 )
    else
        mkdir -p "$(dirname "$path")"
        git clone "$url" "$path"
        ( cd "$path" \
            && git checkout "$commit" \
            && git submodule update --init --recursive --depth 1 )
    fi
}

# 1. Sync submodules
step "Sync submodules"
sync_submodule "SRC/GIT/rpcs3" "$RPCS3_URL" "$RPCS3_COMMIT"
sync_submodule "SRC/GIT/rpcn"  "$RPCN_URL"  "$RPCN_COMMIT"

# 2. Apply patches (ordered list from SRC/PATCH/series)
step "Apply patches"
bash "$REPO_ROOT/SRC/apply-patches.sh"

# 3. Build RPCS3 via cmake + ninja
step "Build RPCS3"
RPCS3_BUILD="SRC/GIT/rpcs3/build"
mkdir -p "$RPCS3_BUILD"
( cd "$RPCS3_BUILD" \
    && cmake .. -GNinja \
        -DCMAKE_BUILD_TYPE=Release \
        -DUSE_NATIVE_INSTRUCTIONS=OFF \
        -DUSE_SYSTEM_FFMPEG=ON \
    && ninja )

# 4. Build RPCN via cargo
step "Build RPCN"
( cd "SRC/GIT/rpcn" && cargo build --release )

# 5. Deploy artifacts
step "Deploy artifacts"
RPCS3_BIN="SRC/GIT/rpcs3/build/bin/rpcs3"
RPCN_BIN="SRC/GIT/rpcn/target/release/rpcn"

[ -x "$RPCS3_BIN" ] || { echo "RPCS3 build output not found at $RPCS3_BIN" >&2; exit 1; }
[ -x "$RPCN_BIN" ]  || { echo "RPCN build output not found at $RPCN_BIN" >&2;  exit 1; }

mkdir -p "$RPCS3_DEPLOY" "$RPCN_DEPLOY"

# Mirror the RPCS3 bin/ tree, excluding portable/ (preserves user state) and
# routing GuiConfigs/ + Icons/ under portable/ where the emulator looks for
# them in portable mode.
RPCS3_BIN_SRC="SRC/GIT/rpcs3/build/bin"
if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
        --exclude='portable/' \
        --exclude='GuiConfigs/' \
        --exclude='Icons/' \
        "$RPCS3_BIN_SRC/" "$RPCS3_DEPLOY/"
    for sub in GuiConfigs Icons; do
        if [ -d "$RPCS3_BIN_SRC/$sub" ]; then
            mkdir -p "$RPCS3_DEPLOY/portable/$sub"
            rsync -a "$RPCS3_BIN_SRC/$sub/" "$RPCS3_DEPLOY/portable/$sub/"
        fi
    done
else
    echo "WARNING: rsync not installed; falling back to cp." >&2
    find "$RPCS3_BIN_SRC" -mindepth 1 -maxdepth 1 \
        ! -name portable ! -name GuiConfigs ! -name Icons \
        -exec cp -a {} "$RPCS3_DEPLOY/" \;
    for sub in GuiConfigs Icons; do
        if [ -d "$RPCS3_BIN_SRC/$sub" ]; then
            mkdir -p "$RPCS3_DEPLOY/portable/$sub"
            cp -a "$RPCS3_BIN_SRC/$sub/." "$RPCS3_DEPLOY/portable/$sub/"
        fi
    done
fi

cp -f "$RPCN_BIN" "$RPCN_DEPLOY/rpcn"
chmod +x "$RPCN_DEPLOY/rpcn"

# 6. Package
step "Package"
bash "$REPO_ROOT/package.sh"

step "Done"
ls -lh "$REPO_ROOT"/OEL-SRC-*.tar.xz "$REPO_ROOT"/OEL-DOCKER-*.tar.xz 2>/dev/null || true
