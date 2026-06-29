"""TSS file management: presence check and local copy."""
import os
import shutil

from . import games

TSS_FILES = [f"{games.ACTIVE.comm_id}-{i}.tss" for i in range(15)]


def count_present(tss_dir: str) -> int:
    """Return how many of the 15 expected TSS files exist in tss_dir."""
    return sum(1 for name in TSS_FILES if os.path.exists(os.path.join(tss_dir, name)))


def list_status(tss_dir: str) -> list[tuple[str, bool]]:
    """Return [(filename, present), ...] for all 15 TSS files."""
    return [
        (name, os.path.exists(os.path.join(tss_dir, name)))
        for name in TSS_FILES
    ]


def copy_tss(
    source_dir: str,
    rpcs3_tss_dir: str,
    rpcn_tss_dir: str | None = None,
) -> int:
    """Copy present TSS files from source_dir to rpcs3_tss_dir (and optionally rpcn_tss_dir).

    Returns the number of files copied.
    """
    os.makedirs(rpcs3_tss_dir, exist_ok=True)
    if rpcn_tss_dir:
        os.makedirs(rpcn_tss_dir, exist_ok=True)

    copied = 0
    for name in TSS_FILES:
        src = os.path.join(source_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(rpcs3_tss_dir, name))
            if rpcn_tss_dir:
                shutil.copy2(src, os.path.join(rpcn_tss_dir, name))
            copied += 1
    return copied
