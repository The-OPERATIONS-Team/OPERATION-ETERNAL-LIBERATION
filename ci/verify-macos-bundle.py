#!/usr/bin/env python3
"""Verify that a packaged OEL Apple Silicon client is self-contained."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


FORBIDDEN_RUNTIME_NAMES = {
    "cert.pem",
    "key.pem",
    "rpcn.yml",
    "settings.json",
}


def run(*args: str) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout


def fail(message: str) -> None:
    raise RuntimeError(message)


def verify_symlinks(root: Path) -> None:
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            target = path.resolve(strict=True)
        except FileNotFoundError:
            fail(f"broken symlink: {path}")
        if target != resolved_root and resolved_root not in target.parents:
            fail(f"symlink escapes package: {path} -> {target}")


def verify_private_data(root: Path) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        lower_parts = {part.lower() for part in path.parts}
        if path.name in FORBIDDEN_RUNTIME_NAMES or path.suffix.lower() == ".tss":
            fail(f"private runtime data included: {path}")
        if "dev_flash" in lower_parts or "dev_hdd0" in lower_parts:
            fail(f"firmware or game data included: {path}")


def verify_macho(path: Path, forbidden_prefixes: list[str]) -> bool:
    description = run("/usr/bin/file", "-b", str(path))
    if "Mach-O" not in description:
        return False

    arches = run("/usr/bin/lipo", "-archs", str(path)).split()
    if "arm64" not in arches:
        fail(f"Mach-O lacks arm64 slice: {path} ({' '.join(arches)})")

    metadata = run("/usr/bin/otool", "-L", str(path))
    metadata += run("/usr/bin/otool", "-l", str(path))
    forbidden = ["/opt/homebrew", "/usr/local", "/tmp/Qt", *forbidden_prefixes]
    for prefix in forbidden:
        if prefix and prefix in metadata:
            fail(f"non-portable load path {prefix!r} in {path}")
    return True


def verify_moltenvk(rpcs3_app: Path) -> None:
    manifests = list(rpcs3_app.rglob("MoltenVK_icd.json"))
    if len(manifests) != 1:
        fail(f"expected one MoltenVK manifest, found {len(manifests)}")
    manifest = manifests[0]
    data = json.loads(manifest.read_text(encoding="utf-8"))
    library_path = data.get("ICD", {}).get("library_path")
    if not library_path:
        fail("MoltenVK manifest has no library_path")
    library = (manifest.parent / library_path).resolve()
    if not library.is_file():
        fail(f"MoltenVK manifest target is missing: {library}")
    dylibs = [p for p in rpcs3_app.rglob("libMoltenVK.dylib") if p.is_file()]
    if len(dylibs) != 1:
        fail(f"expected one bundled libMoltenVK.dylib, found {len(dylibs)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("client_root", type=Path)
    parser.add_argument("--forbid-prefix", action="append", default=[])
    args = parser.parse_args()

    root = args.client_root.resolve()
    rpcs3_app = root / "_app" / "RPCS3" / "RPCS3.app"
    wrapper_app = root / "OPERATION ETERNAL LIBERATION.app"
    if not rpcs3_app.is_dir():
        fail(f"missing {rpcs3_app}")
    if not wrapper_app.is_dir():
        fail(f"missing {wrapper_app}")

    verify_symlinks(root)
    verify_private_data(root)

    macho_count = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            macho_count += int(verify_macho(path, args.forbid_prefix))
    if macho_count == 0:
        fail("no Mach-O files found")

    verify_moltenvk(rpcs3_app)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(rpcs3_app))
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(wrapper_app))

    print(f"macOS bundle verification passed ({macho_count} Mach-O files).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
