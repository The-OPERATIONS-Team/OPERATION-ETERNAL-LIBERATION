#!/usr/bin/env bash
# Stamp the build version into OEL.iss and BIN/_app/app/paths.py.
#
# Logic:
#   - On a tag push (GITHUB_REF=refs/tags/X.Y.Z[.W]), the tag IS the version.
#     The tag is checked against the AppVersion already baked into OEL.iss
#     so a forgotten bump fails CI loudly instead of producing a mislabeled
#     installer.
#   - On a main-branch build the version is "<AppVersion>-<short-sha>".
#   - On any other branch it is "<AppVersion>-<branch>-<short-sha>" so
#     parallel branches don't produce indistinguishable artifact names.
#
# Re-runnable: the AppVersion / VERSION regexes are anchored on unique
# line prefixes, so running this twice on the same tree is a no-op the
# second time.
#
# Sets VERSION in GITHUB_ENV when running under GitHub Actions, so later
# workflow steps can reference it (release notes, artifact names, etc.).
#
# Designed for both Linux runners and Git Bash on Windows runners. Both
# ship GNU sed, which is what the `sed -i.bak` invocation expects.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ISS="$ROOT/OEL.iss"
LAUNCHER="$ROOT/BIN/_app/app/paths.py"

# Base version. The #define line in OEL.iss is the single source of truth;
# app/paths.py just mirrors it. Bumping the release is still a one-line edit.
APP_VER="$(awk -F'"' '/^#define AppVersion/ {print $2; exit}' "$ISS")"
if [ -z "$APP_VER" ]; then
    echo "ERROR: could not parse AppVersion from $ISS" >&2
    exit 1
fi

# Short SHA. Fall back to a placeholder so this still works for someone
# building from an unpacked OEL-SRC tarball with no .git directory.
SHORT_SHA="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "unknown")"

if [[ "${GITHUB_REF:-}" == refs/tags/* ]]; then
    TAG="${GITHUB_REF#refs/tags/}"
    if [ "$TAG" != "$APP_VER" ] && [[ "$TAG" != "${APP_VER}-"* ]]; then
        cat >&2 <<EOF
ERROR: release tag "$TAG" does not match AppVersion "$APP_VER" in OEL.iss.
The tag must equal AppVersion exactly (e.g. "$APP_VER") or start with
"$APP_VER-" for an experimental build (e.g. "${APP_VER}-experimental-1").
Bump the AppVersion (and re-commit) before pushing the release tag.
EOF
        exit 1
    fi
    VERSION="$TAG"
else
    # Branch name. Prefer GITHUB_HEAD_REF (PR source branch), then
    # GITHUB_REF_NAME (push / workflow_dispatch), then git directly (local).
    BRANCH="${GITHUB_HEAD_REF:-${GITHUB_REF_NAME:-}}"
    if [ -z "$BRANCH" ]; then
        BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
    fi
    BRANCH="${BRANCH//\//-}"  # sanitize feature/foo -> feature-foo

    if [ -n "$BRANCH" ] && [ "$BRANCH" != "main" ] && [ "$BRANCH" != "HEAD" ]; then
        VERSION="${APP_VER}-${BRANCH}-${SHORT_SHA}"
    else
        VERSION="${APP_VER}-${SHORT_SHA}"
    fi
fi

# In-place stamp. Anchors on unique prefixes so this is idempotent.
sed -i.bak -E "s/^(#define AppVersion ).*/\\1\"${VERSION}\"/" "$ISS"
sed -i.bak -E "s/^(VERSION[[:space:]]*)= \"[^\"]*\"/\1= \"${VERSION}\"/" "$LAUNCHER"
rm -f "$ISS.bak" "$LAUNCHER.bak"

# Fail loud if either stamp was a no-op, e.g. a refactor moved the VERSION line.
for f in "$ISS" "$LAUNCHER"; do
    if ! grep -qF "\"${VERSION}\"" "$f"; then
        echo "ERROR: version stamp did not take effect in $f" >&2
        exit 1
    fi
done

echo "Stamped build version: $VERSION"

if [ -n "${GITHUB_ENV:-}" ]; then
    echo "VERSION=$VERSION" >> "$GITHUB_ENV"
fi
