#!/usr/bin/env python3
"""Remove build-machine Homebrew paths from a deployed macOS app bundle."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


FORBIDDEN_PREFIXES = ("/opt/homebrew", "/usr/local")


def output(*args: str) -> str:
    return subprocess.run(
        args, check=True, capture_output=True, text=True
    ).stdout


def is_macho(path: Path) -> bool:
    return "Mach-O" in output("/usr/bin/file", "-b", str(path))


def dependencies(path: Path) -> list[str]:
    lines = output("/usr/bin/otool", "-L", str(path)).splitlines()[1:]
    return [line.strip().split(" (", 1)[0] for line in lines if line.strip()]


def install_id(path: Path) -> str | None:
    lines = output("/usr/bin/otool", "-D", str(path)).splitlines()
    return lines[1].strip() if len(lines) > 1 else None


def rpaths(path: Path) -> list[str]:
    lines = output("/usr/bin/otool", "-l", str(path)).splitlines()
    found: list[str] = []
    for index, line in enumerate(lines):
        if line.strip() != "cmd LC_RPATH":
            continue
        for candidate in lines[index + 1:index + 4]:
            candidate = candidate.strip()
            if candidate.startswith("path "):
                found.append(candidate[5:].split(" (offset", 1)[0])
                break
    return found


def bundled_reference(dependency: str, frameworks: Path) -> tuple[Path, str]:
    dep_path = Path(dependency)
    framework_index = next(
        (
            index for index, part in enumerate(dep_path.parts)
            if part.endswith(".framework")
        ),
        None,
    )
    if framework_index is None:
        relative = Path(dep_path.name)
    else:
        relative = Path(*dep_path.parts[framework_index:])
    return frameworks / relative, f"@rpath/{relative.as_posix()}"


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} RPCS3.app", file=sys.stderr)
        return 2

    app = Path(sys.argv[1]).resolve()
    frameworks = app / "Contents" / "Frameworks"
    changed = 0
    for path in app.rglob("*"):
        if not path.is_file() or path.is_symlink() or not is_macho(path):
            continue

        edits: list[str] = []
        current_id = install_id(path)
        if current_id and current_id.startswith(FORBIDDEN_PREFIXES):
            bundled, replacement = bundled_reference(current_id, frameworks)
            if not bundled.exists():
                raise RuntimeError(
                    f"cannot rewrite unbundled install name {current_id} in {path}"
                )
            edits.extend(["-id", replacement])

        for dependency in dependencies(path):
            if not dependency.startswith(FORBIDDEN_PREFIXES):
                continue
            if dependency == current_id:
                continue
            bundled, replacement = bundled_reference(dependency, frameworks)
            if not bundled.exists():
                raise RuntimeError(
                    f"cannot rewrite unbundled dependency {dependency} in {path}"
                )
            edits.extend(["-change", dependency, replacement])

        for entry in rpaths(path):
            if entry.startswith(FORBIDDEN_PREFIXES):
                edits.extend(["-delete_rpath", entry])

        if edits:
            subprocess.run(
                ["/usr/bin/install_name_tool", *edits, str(path)],
                check=True,
            )
            changed += 1

    print(f"Rewrote build-machine load paths in {changed} Mach-O files.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
