#!/usr/bin/env bash
# Provision a self-contained Apple Silicon Python runtime for the macOS client.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-$ROOT/BIN/_app/python}"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
    echo "ERROR: macOS arm64 is required." >&2
    exit 1
fi

PBS_TAG="20260610"
PBS_BUILD="cpython-3.12.13+${PBS_TAG}-aarch64-apple-darwin-install_only_stripped"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${PBS_BUILD}.tar.gz"
PBS_SHA256="f0a7fa7decc75df2b1a789329a44f657c4a15c0a683f197ce46a5cb621bc6ef4"

if [ -x "$TARGET/bin/python3" ]; then
    echo "Bundled Python already present at $TARGET"
else
    echo "Downloading $PBS_BUILD..."
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    curl -fsSL "$PBS_URL" -o "$TMP/python.tar.gz"
    ACTUAL_SHA256="$(shasum -a 256 "$TMP/python.tar.gz" | awk '{print $1}')"
    if [ "$ACTUAL_SHA256" != "$PBS_SHA256" ]; then
        echo "ERROR: Python archive checksum mismatch." >&2
        exit 1
    fi

    echo "Extracting to $TARGET..."
    rm -rf "$TARGET"
    mkdir -p "$(dirname "$TARGET")"
    tar -xzf "$TMP/python.tar.gz" -C "$(dirname "$TARGET")"
    if [ "$(basename "$TARGET")" != "python" ]; then
        mv "$(dirname "$TARGET")/python" "$TARGET"
    fi
fi

echo "Installing pinned launcher dependencies..."
"$TARGET/bin/python3" -m pip install --quiet --upgrade \
    "cryptography==45.0.7" \
    "PySide6-Essentials==6.9.3"

# The launcher does not use Qt SQL. Its optional ODBC driver carries a
# non-portable /usr/local dependency in the upstream wheel.
rm -rf "$TARGET/lib/python3.12/site-packages/PySide6/Qt/plugins/sqldrivers"

# Keep a distinct executable for the elevated server process.
cp -L "$TARGET/bin/python3" "$TARGET/bin/python3-gameserver"
chmod +x "$TARGET/bin/python3-gameserver"

"$TARGET/bin/python3" -c \
    "import PySide6.QtCore, cryptography; print('Bundled Python OK:', __import__('sys').version.split()[0])"
file "$TARGET/bin/python3" | grep -q "arm64"
