#!/usr/bin/env bash
# Build and stage OEL's pinned, patched RPCS3 and RPCN for Apple Silicon.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/SRC"
RPCS3_SRC="$SRC/GIT/rpcs3"
RPCN_SRC="$SRC/GIT/rpcn"
SERIES_MARKER="$SRC/GIT/.oel-patch-series.sha256"
ARTIFACTS="$ROOT/build-macos/artifacts"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
    echo "ERROR: Apple Silicon macOS is required." >&2
    exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
    echo "ERROR: missing required tool: brew" >&2
    exit 1
fi
export PATH="$(brew --prefix protobuf)/bin:$HOME/.cargo/bin:$PATH"

for tool in cmake ninja git cargo rustc protoc 7z curl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: missing required tool: $tool" >&2
        exit 1
    fi
done

# Current RPCS3 deployment uses wget for one fixed download. macOS ships curl,
# so provide the small compatible surface locally instead of adding a package.
COMPAT_BIN="$ROOT/build-macos/compat-bin"
mkdir -p "$COMPAT_BIN"
cat > "$COMPAT_BIN/wget" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/curl -fsSLO "$@"
EOF
chmod +x "$COMPAT_BIN/wget"

# shellcheck disable=SC1091
source "$SRC/pinned-commits.env"
RPCS3_BUILD_COMMIT="${RPCS3_MACOS_COMMIT:-$RPCS3_COMMIT}"

if [ ! -d "$RPCS3_SRC/.git" ] || [ ! -d "$RPCN_SRC/.git" ]; then
    bash "$SRC/clone-git-repos.sh"
fi

if [ "$(git -C "$RPCS3_SRC" rev-parse HEAD)" != "$RPCS3_BUILD_COMMIT" ]; then
    if [ -n "$(git -C "$RPCS3_SRC" status --short --untracked-files=no)" ]; then
        echo "ERROR: RPCS3 source has tracked changes at the wrong revision." >&2
        echo "Use a fresh clone before switching to the macOS pin." >&2
        exit 1
    fi
    git -C "$RPCS3_SRC" checkout --detach "$RPCS3_BUILD_COMMIT"
    git -C "$RPCS3_SRC" submodule update --init --recursive
    rm -f "$SERIES_MARKER"
fi
if [ "$(git -C "$RPCS3_SRC" rev-parse HEAD)" != "$RPCS3_BUILD_COMMIT" ]; then
    echo "ERROR: RPCS3 checkout is not at the macOS pinned commit." >&2
    exit 1
fi
if [ "$(git -C "$RPCN_SRC" rev-parse HEAD)" != "$RPCN_COMMIT" ]; then
    echo "ERROR: RPCN checkout is not at the pinned commit." >&2
    exit 1
fi

SERIES_SHA="$(shasum -a 256 "$SRC/PATCH/series" "$SRC/PATCH/RPCS3/"*.patch \
    "$SRC/PATCH/RPCN/"*.patch | shasum -a 256 | awk '{print $1}')"
CURRENT_MARKER="$(cat "$SERIES_MARKER" 2>/dev/null || true)"
if [ "$CURRENT_MARKER" != "$SERIES_SHA" ]; then
    if [ -n "$(git -C "$RPCS3_SRC" status --short --untracked-files=no)" ] \
            || [ -n "$(git -C "$RPCN_SRC" status --short --untracked-files=no)" ]; then
        echo "ERROR: source trees contain unmarked tracked changes." >&2
        echo "Use fresh pinned clones before applying the OEL patch series." >&2
        exit 1
    fi
    bash "$SRC/apply-patches.sh"
    printf '%s\n' "$SERIES_SHA" > "$SERIES_MARKER"
fi

BREW_PREFIX="$(brew --prefix)"
LINKED_FORMULAE=()
for formula in ffmpeg fmt protobuf; do
    if [ -L "$BREW_PREFIX/var/homebrew/linked/$formula" ]; then
        LINKED_FORMULAE+=("$formula")
    fi
    if brew list --versions "$formula" >/dev/null 2>&1; then
        brew unlink "$formula" >/dev/null 2>&1 || true
    fi
done

restore_brew_links() {
    for formula in "${LINKED_FORMULAE[@]}"; do
        brew link --overwrite "$formula" >/dev/null 2>&1 || true
    done
}
trap restore_brew_links EXIT

mkdir -p "$ARTIFACTS" "$ROOT/build-macos/ccache"
if [ -f "$RPCS3_SRC/build/CMakeCache.txt" ] \
        && ! grep -Fq "CMAKE_HOME_DIRECTORY:INTERNAL=$RPCS3_SRC" \
            "$RPCS3_SRC/build/CMakeCache.txt"; then
    echo "ERROR: existing RPCS3 build directory belongs to another source tree." >&2
    exit 1
fi

QT_VER="6.11.1"
QT_PREFIX="$(brew --prefix qt)"
LLVM_PREFIX="$(brew --prefix llvm@21)"
SDL_PREFIX="$(brew --prefix sdl3)"
OPENCV_PREFIX="$(brew --prefix opencv@4)"
VULKAN_SDK="$ROOT/build-macos/VulkanSDK"
mkdir -p "$VULKAN_SDK/lib"
ln -sfn "$(brew --prefix vulkan-headers)/include" "$VULKAN_SDK/include"
ln -sfn "$(brew --prefix vulkan-loader)/lib/libvulkan.dylib" \
    "$VULKAN_SDK/lib/libvulkan.dylib"

# deploy-mac.sh reads translations from the layout used by RPCS3 CI. Recreate
# only that portion with Homebrew's matching qttranslations package.
QT_CI_ROOT="$RPCS3_SRC/qt-downloader/$QT_VER/clang_64"
rm -rf "$QT_CI_ROOT"
mkdir -p "$QT_CI_ROOT"
ln -s "$(brew --prefix qttranslations)/share/qt/translations" \
    "$QT_CI_ROOT/translations"

COMM_TAG="$(awk '/version{.*}/ { printf("%d.%d.%d", $5, $6, $7) }' \
    "$RPCS3_SRC/rpcs3/rpcs3_version.cpp")"
COMM_COUNT="$(git -C "$RPCS3_SRC" rev-list --count HEAD)"
COMM_HASH="$(git -C "$RPCS3_SRC" rev-parse --short=8 HEAD)"
LVER="${COMM_TAG}-${COMM_COUNT}-${COMM_HASH}"

PATH="$LLVM_PREFIX/bin:$PATH" \
CC=clang \
CXX=clang++ \
Qt6_DIR="$QT_PREFIX/lib/cmake/Qt6" \
SDL3_DIR="$SDL_PREFIX/lib/cmake/SDL3" \
LLVM_DIR="$LLVM_PREFIX/lib/cmake/llvm" \
OpenCV_DIR="$OPENCV_PREFIX/lib/cmake/opencv4" \
VULKAN_SDK="$VULKAN_SDK" \
CCACHE_DIR="$ROOT/build-macos/ccache" \
LDFLAGS="-L$LLVM_PREFIX/lib/c++ -L$LLVM_PREFIX/lib/unwind -lunwind" \
cmake \
    -S "$RPCS3_SRC" \
    -B "$RPCS3_SRC/build" \
    -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_RPCS3_TESTS=OFF \
    -DRUN_RPCS3_TESTS=OFF \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=14.4 \
    -DCMAKE_OSX_SYSROOT="$(xcrun --sdk macosx --show-sdk-path)" \
    -DMACOSX_BUNDLE_SHORT_VERSION_STRING="$COMM_TAG" \
    -DMACOSX_BUNDLE_BUNDLE_VERSION="$COMM_COUNT" \
    -DMACDEPLOYQT_EXECUTABLE="$QT_PREFIX/bin/macdeployqt" \
    -DQt6_DIR="$QT_PREFIX/lib/cmake/Qt6" \
    -DSDL3_DIR="$SDL_PREFIX/lib/cmake/SDL3" \
    -DLLVM_DIR="$LLVM_PREFIX/lib/cmake/llvm" \
    -DOpenCV_DIR="$OPENCV_PREFIX/lib/cmake/opencv4" \
    -DSTATIC_LINK_LLVM=ON \
    -DUSE_SDL=ON \
    -DUSE_DISCORD_RPC=ON \
    -DUSE_AUDIOUNIT=ON \
    -DUSE_SYSTEM_FFMPEG=OFF \
    -DUSE_SYSTEM_PROTOBUF=OFF \
    -DUSE_NATIVE_INSTRUCTIONS=OFF \
    -DUSE_PRECOMPILED_HEADERS=OFF \
    -DUSE_SYSTEM_MVK=ON \
    -DUSE_SYSTEM_SDL=ON \
    -DUSE_SYSTEM_OPENCV=ON

PATH="$LLVM_PREFIX/bin:$PATH" \
CCACHE_DIR="$ROOT/build-macos/ccache" \
LDFLAGS="-L$LLVM_PREFIX/lib/c++ -L$LLVM_PREFIX/lib/unwind -lunwind" \
cmake --build "$RPCS3_SRC/build" --parallel 6

# Reuse the pinned upstream deployment step for MoltenVK, load-path rewriting,
# translation deployment, optimization, and ad-hoc signing.
rm -rf "$RPCS3_SRC/build/bin/MoltenVK"
(
    cd "$RPCS3_SRC"
    export BREW_PATH="$BREW_PREFIX"
    export LLVM_COMPILER_VER="21"
    export WORKDIR="$RPCS3_SRC"
    export QT_VER
    export LVER
    export PATH="$COMPAT_BIN:$PATH"
    export BUILD_ARTIFACTSTAGINGDIRECTORY="$ARTIFACTS"
    export RELEASE_MESSAGE="$ROOT/build-macos/GitHubReleaseMessage.txt"
    .ci/deploy-mac.sh
)
python3 "$ROOT/ci/fix-macos-load-paths.py" \
    "$RPCS3_SRC/build/bin/RPCS3.app"
codesign --force --deep --sign - "$RPCS3_SRC/build/bin/RPCS3.app"

restore_brew_links
trap - EXIT

RPCS3_APP="$RPCS3_SRC/build/bin/RPCS3.app"
if [ ! -d "$RPCS3_APP" ]; then
    echo "ERROR: RPCS3 build did not produce $RPCS3_APP" >&2
    exit 1
fi
mkdir -p "$ROOT/BIN/_app/RPCS3/portable"
rm -rf "$ROOT/BIN/_app/RPCS3/RPCS3.app"
ditto "$RPCS3_APP" "$ROOT/BIN/_app/RPCS3/RPCS3.app"
for directory in GuiConfigs Icons; do
    if [ -d "$RPCS3_SRC/bin/$directory" ]; then
        ditto "$RPCS3_SRC/bin/$directory" \
              "$ROOT/BIN/_app/RPCS3/portable/$directory"
    fi
done

RPCN_TARGET="$ROOT/build-macos/rpcn-target"
(
    cd "$RPCN_SRC"
    CARGO_TARGET_DIR="$RPCN_TARGET" cargo build --locked --release
)
mkdir -p "$ROOT/BIN/_app/rpcn"
cp "$RPCN_TARGET/release/rpcn" "$ROOT/BIN/_app/rpcn/rpcn"
chmod +x "$ROOT/BIN/_app/rpcn/rpcn"

file "$ROOT/BIN/_app/RPCS3/RPCS3.app/Contents/MacOS/rpcs3" | grep -q "arm64"
file "$ROOT/BIN/_app/rpcn/rpcn" | grep -q "arm64"
codesign --verify --deep --strict --verbose=2 \
    "$ROOT/BIN/_app/RPCS3/RPCS3.app"

echo "Staged Apple Silicon RPCS3 and RPCN under BIN/_app."
