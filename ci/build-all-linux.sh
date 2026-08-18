#!/usr/bin/env bash
# Full Linux build pipeline for a local builder machine.
# Resets submodules to pinned commits + reapplies patches every run for
# reproducible builds, then mirrors the Linux job in
# .github/workflows/build.yml: rpcs3 AppImage in upstream's CI container,
# rpcn via cargo, bundled Python, package.sh.
#
# Prereqs: git, docker (user in docker group), curl, xz, python3,
# ~/.cargo/bin/cargo (rustup), protoc on PATH or in ~/.local/bin.
#
# Env knobs:
#   OEL_CCACHE_DIR   ccache volume (default: <repo>/../ccache)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

step() { echo; echo "=== $1 ==="; }

reclaim_ownership() {
    # The rpcs3 container runs as root; an interrupted run leaves root-owned
    # files that break the next submodule sync. Reclaim via docker (no sudo).
    local paths=()
    [ -d "$ROOT/SRC/GIT/rpcs3" ] && paths+=(-v "$ROOT/SRC/GIT/rpcs3:/r0")
    [ -d "$ROOT/artifacts" ]     && paths+=(-v "$ROOT/artifacts:/r1")
    [ ${#paths[@]} -eq 0 ] && return 0
    docker run --rm "${paths[@]}" busybox \
        sh -c "chown -R $(id -u):$(id -g) /r0 /r1 2>/dev/null || true"
}

# Pinned commits -- shared with clone-git-repos.sh (tolerate CRLF).
RPCS3_URL=""; RPCS3_COMMIT=""; RPCN_URL=""; RPCN_COMMIT=""
while IFS='=' read -r key val; do
    case "$key" in
        RPCS3_URL|RPCS3_COMMIT|RPCN_URL|RPCN_COMMIT) printf -v "$key" '%s' "$val" ;;
    esac
done < <(tr -d '\r' < SRC/pinned-commits.env)

sync_submodule() {
    local path="$1" url="$2" commit="$3"
    if [ -d "$path/.git" ]; then
        # update --force (no --init: the container picks which to init):
        # a submodule whose worktree was emptied by an interrupted run is
        # otherwise skipped because its recorded HEAD matches the gitlink.
        ( cd "$path" \
            && git reset --hard HEAD \
            && git clean -ffdx \
            && git fetch origin \
            && git checkout "$commit" \
            && git submodule update --force )
    else
        mkdir -p "$(dirname "$path")"
        git clone "$url" "$path"
        ( cd "$path" && git checkout "$commit" )
    fi
}

step "Sync submodules"
reclaim_ownership
sync_submodule SRC/GIT/rpcs3 "$RPCS3_URL" "$RPCS3_COMMIT"
sync_submodule SRC/GIT/rpcn  "$RPCN_URL"  "$RPCN_COMMIT"

step "Apply patches"
bash SRC/apply-patches.sh

step "Build RPCS3 (upstream CI container)"
CCACHE_DIR="${OEL_CCACHE_DIR:-$ROOT/../ccache}"
mkdir -p "$CCACHE_DIR"
ARTDIR_HOST="$ROOT/artifacts"
mkdir -p "$ARTDIR_HOST"

DOCKER_IMG="rpcs3/rpcs3-ci-jammy:2.1"
docker pull --quiet "$DOCKER_IMG"
# BUILD_REPOSITORY_NAME / BUILD_SOURCEBRANCHNAME are intentionally omitted below:
# leaving them unset keeps RPCS3_GIT_FULL_BRANCH at "local_build", which suppresses
# the experimental-build warning and the auto-update notification.
docker run --rm \
    -v "$ROOT/SRC/GIT/rpcs3:/rpcs3" \
    -v "$CCACHE_DIR:/root/.ccache" \
    -v "$ARTDIR_HOST:/rpcs3-artifacts" \
    -e APPDIR=/rpcs3/build/appdir \
    -e ARTDIR=/rpcs3-artifacts \
    -e RELEASE_MESSAGE=/rpcs3/GitHubReleaseMessage.txt \
    -e COMPILER=clang \
    -e DEPLOY_APPIMAGE=true \
    -e RUN_UNIT_TESTS=OFF \
    -e BUILD_PR_NUMBER= \
    -e BUILD_SOURCEVERSION="$(git rev-parse HEAD)" \
    -e BUILD_ARTIFACTSTAGINGDIRECTORY=/rpcs3-artifacts \
    "$DOCKER_IMG" \
    /rpcs3/.ci/build-linux.sh

# The container runs as root; reclaim ownership without host sudo.
docker run --rm \
    -v "$ROOT/SRC/GIT/rpcs3:/s" -v "$ARTDIR_HOST:/a" -v "$CCACHE_DIR:/c" \
    busybox chown -R "$(id -u):$(id -g)" /s /a /c

step "Build RPCN"
( cd SRC/GIT/rpcn && cargo build --release )

step "Stage rpcs3 + rpcn into BIN/_app"
mkdir -p BIN/_app/RPCS3/portable BIN/_app/rpcn
rm -f BIN/_app/RPCS3/*.AppImage
cp "$ARTDIR_HOST"/*.AppImage BIN/_app/RPCS3/
for sub in GuiConfigs Icons; do
    if [ -d "SRC/GIT/rpcs3/bin/$sub" ]; then
        rm -rf "BIN/_app/RPCS3/portable/$sub"
        cp -r "SRC/GIT/rpcs3/bin/$sub" "BIN/_app/RPCS3/portable/$sub"
    fi
done
cp SRC/GIT/rpcn/target/release/rpcn BIN/_app/rpcn/

step "Provision bundled Python runtime"
bash ci/provision-linux-python.sh

step "Package"
bash package.sh

step "Done"
ls -lh OP-ETERNAL-*-linux-x86_64.tar.xz OEL-SRC-*.tar.xz OEL-DOCKER-*.tar.xz
