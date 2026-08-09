#!/usr/bin/env bash
# Clone RPCS3 and RPCN at the pinned baseline commits.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$SRC/pinned-commits.env" ]; then
    echo "ERROR: $SRC/pinned-commits.env not found." >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$SRC/pinned-commits.env"
# .gitattributes pins this file to LF, but a clone predating that, or an editor,
# can still leave CRLF here, and the carriage return then rides along on the URL.
RPCS3_URL="${RPCS3_URL%$'\r'}";  RPCS3_COMMIT="${RPCS3_COMMIT%$'\r'}"
RPCN_URL="${RPCN_URL%$'\r'}";    RPCN_COMMIT="${RPCN_COMMIT%$'\r'}"

echo "============================================================"
echo " ACI-RPCS3 -- Clone source repos at patch baseline"
echo "============================================================"
echo

for d in rpcs3 rpcn; do
    if [ -d "$SRC/GIT/$d" ]; then
        echo "ERROR: GIT/$d already exists. Run reset-git-repos.sh instead." >&2
        exit 1
    fi
done

mkdir -p "$SRC/GIT"

echo "[1/4] Cloning RPCS3 (this may take a while)..."
git clone "$RPCS3_URL" "$SRC/GIT/rpcs3"
echo "Done."
echo

echo "[2/4] Checking out $RPCS3_COMMIT and initialising submodules..."
( cd "$SRC/GIT/rpcs3" && git checkout "$RPCS3_COMMIT" && git submodule update --init --recursive )
echo "Done."
echo

echo "[3/4] Cloning RPCN..."
git clone "$RPCN_URL" "$SRC/GIT/rpcn"
echo "Done."
echo

echo "[4/4] Checking out $RPCN_COMMIT..."
( cd "$SRC/GIT/rpcn" && git checkout "$RPCN_COMMIT" )
echo "Done."
echo

echo "============================================================"
echo " Both repos cloned. Run apply-patches.sh next."
echo "============================================================"
