#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP="$ROOT/_app"
PYTHON="$APP/python/bin/python3"
GAMESERVER_PYTHON="$APP/python/bin/python3-gameserver"
MOLTENVK_ICD="$APP/RPCS3/RPCS3.app/Contents/Resources/vulkan/icd.d/MoltenVK_icd.json"

if [ "$(uname -m)" != "arm64" ]; then
    echo "ERROR: This OEL package requires an Apple Silicon Mac." >&2
    exit 1
fi

if [ ! -x "$PYTHON" ]; then
    bash "$APP/setup.sh"
fi

if [ ! -x "$GAMESERVER_PYTHON" ]; then
    cp -L "$PYTHON" "$GAMESERVER_PYTHON"
fi

if [ -f "$MOLTENVK_ICD" ]; then
    export VK_ICD_FILENAMES="$MOLTENVK_ICD"
fi
export PYTHONNOUSERSITE=1

# Generate local TLS files before the privileged server starts so they remain
# owned and writable by the current user.
if [ ! -f "$APP/gameserver/cert.pem" ] || [ ! -f "$APP/gameserver/key.pem" ]; then
    (
        cd "$APP/gameserver"
        "$PYTHON" -c "import opeternal_listener as server; server.ensure_cert()"
    )
fi

cd "$ROOT"
exec "$PYTHON" "$APP/launcher.py" "$@"
