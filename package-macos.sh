#!/usr/bin/env bash
# Build a complete Apple Silicon OEL client archive from staged binaries.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(awk -F'"' '/^#define AppVersion/ {print $2; exit}' "$ROOT/OEL.iss")"
RPCS3_APP="$ROOT/BIN/_app/RPCS3/RPCS3.app"
RPCN_BIN="$ROOT/BIN/_app/rpcn/rpcn"
PYTHON_DIR="$ROOT/BIN/_app/python"
OUTPUT="$ROOT/OP-ETERNAL-$VERSION-macos-arm64.tar.xz"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
    echo "ERROR: package-macos.sh must run on Apple Silicon macOS." >&2
    exit 1
fi
if [ ! -d "$RPCS3_APP" ]; then
    echo "ERROR: stage the patched RPCS3.app at $RPCS3_APP first." >&2
    exit 1
fi
if [ ! -x "$RPCN_BIN" ]; then
    echo "ERROR: stage the arm64 RPCN executable at $RPCN_BIN first." >&2
    exit 1
fi
if [ ! -x "$PYTHON_DIR/bin/python3" ]; then
    bash "$ROOT/ci/provision-macos-python.sh" "$PYTHON_DIR"
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
CLIENT="$STAGE/OPERATION-ETERNAL-LIBERATION"

mkdir -p \
    "$CLIENT/TSS" \
    "$CLIENT/_app/RPCS3/portable" \
    "$CLIENT/_app/rpcn" \
    "$CLIENT/_app/gameserver" \
    "$CLIENT/_app/data"

cp "$ROOT/BIN/Play OPERATION ETERNAL LIBERATION (macOS).command" "$CLIENT/"
cp "$ROOT/BIN/READ_ME_FIRST.md" "$CLIENT/"
ditto "$ROOT/packaging/macos/OPERATION ETERNAL LIBERATION.app" \
      "$CLIENT/OPERATION ETERNAL LIBERATION.app"

cp "$ROOT/BIN/_app/launcher.py" "$ROOT/BIN/_app/setup.sh" "$CLIENT/_app/"
for directory in app assets modules patches tools viewmodels views workers; do
    ditto "$ROOT/BIN/_app/$directory" "$CLIENT/_app/$directory"
done
cp "$ROOT/BIN/_app/data/game_manifest.json" "$CLIENT/_app/data/"

cp "$ROOT/BIN/_app/gameserver/opeternal_listener.py" \
   "$ROOT/BIN/_app/gameserver/gameserver.sh" \
   "$CLIENT/_app/gameserver/"
if [ -d "$ROOT/BIN/_app/gameserver/community" ]; then
    ditto "$ROOT/BIN/_app/gameserver/community" "$CLIENT/_app/gameserver/community"
fi

ditto "$PYTHON_DIR" "$CLIENT/_app/python"
ditto "$RPCS3_APP" "$CLIENT/_app/RPCS3/RPCS3.app"
for directory in GuiConfigs Icons; do
    if [ -d "$ROOT/BIN/_app/RPCS3/portable/$directory" ]; then
        ditto "$ROOT/BIN/_app/RPCS3/portable/$directory" \
              "$CLIENT/_app/RPCS3/portable/$directory"
    fi
done

cp "$RPCN_BIN" \
   "$ROOT/BIN/_app/rpcn/rpcn.cfg" \
   "$ROOT/BIN/_app/rpcn/scoreboards.cfg" \
   "$ROOT/BIN/_app/rpcn/server_redirs.cfg" \
   "$ROOT/BIN/_app/rpcn/servers.cfg" \
   "$CLIENT/_app/rpcn/"

# Strip local interpreter and Finder artifacts from copied source directories.
python3 - "$CLIENT" <<'PY'
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
for path in root.rglob("__pycache__"):
    if path.is_dir():
        shutil.rmtree(path)
for path in root.rglob(".DS_Store"):
    path.unlink(missing_ok=True)
PY

chmod +x \
    "$CLIENT/Play OPERATION ETERNAL LIBERATION (macOS).command" \
    "$CLIENT/OPERATION ETERNAL LIBERATION.app/Contents/MacOS/oel-launcher" \
    "$CLIENT/_app/setup.sh" \
    "$CLIENT/_app/gameserver/gameserver.sh" \
    "$CLIENT/_app/python/bin/python3" \
    "$CLIENT/_app/python/bin/python3-gameserver" \
    "$CLIENT/_app/rpcn/rpcn"

WRAPPER_PLIST="$CLIENT/OPERATION ETERNAL LIBERATION.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$WRAPPER_PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$WRAPPER_PLIST"

# Sign after every bundle mutation.
python3 "$ROOT/ci/fix-macos-load-paths.py" "$CLIENT/_app/RPCS3/RPCS3.app"
codesign --force --deep --sign - "$CLIENT/_app/RPCS3/RPCS3.app"
codesign --force --deep --sign - "$CLIENT/OPERATION ETERNAL LIBERATION.app"

VERIFY_ARGS=("$CLIENT" --forbid-prefix "$ROOT")
if [ -n "${OEL_FORBIDDEN_PREFIX:-}" ]; then
    VERIFY_ARGS+=(--forbid-prefix "$OEL_FORBIDDEN_PREFIX")
fi
python3 "$ROOT/ci/verify-macos-bundle.py" "${VERIFY_ARGS[@]}"

rm -f "$OUTPUT" "$OUTPUT.sha256"
COPYFILE_DISABLE=1 tar --no-xattrs -C "$STAGE" -cJf "$OUTPUT" \
    "OPERATION-ETERNAL-LIBERATION"
shasum -a 256 "$OUTPUT" > "$OUTPUT.sha256"

echo "Created:"
echo "  $OUTPUT"
echo "  $OUTPUT.sha256"
