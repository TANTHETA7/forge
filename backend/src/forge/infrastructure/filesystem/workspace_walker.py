"""Shared workspace directory walk.

Purpose:       One "walk this workspace, skipping VCS/dependency/build noise"
                implementation, used by both the Phase 2 repository metadata
                scanner and the Phase 3 parser's file discovery — extracted from
                `infrastructure/scanner/metadata_scanner.py`'s original private
                `_walk`/`_IGNORED_DIR_NAMES` (behavior-preserving: its existing
                tests pass unchanged against the refactored version) rather than
                writing a second copy for Phase 3.
Responsibility: A single read-only recursive directory walk.
Depends on:    pathlib (stdlib).
Depended on by: infrastructure/scanner/metadata_scanner.py,
                infrastructure/parsing/file_discovery.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

# Directories whose contents are noise for both a metadata summary and parsing —
# VCS internals, dependency caches, build output.
IGNORED_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}


def walk_workspace(root: Path) -> Iterator[Path]:
    """Yield every file and directory under `root` (depth-first), excluding
    `IGNORED_DIR_NAMES` and never descending into or yielding a symlink.

    Not following symlinks is more than tidiness: Phase 2's ZIP importer rejects
    symlink entries at extraction time (infrastructure/sources/zip_source.py),
    but `git clone` does not go through that hardening — a cloned repository can
    legitimately contain a symlink pointing outside the workspace. Refusing to
    follow any symlink here is what keeps every consumer of this walk (the
    metadata scanner, the parser's file discovery) from ever reading a path
    outside the isolated workspace, regardless of which Phase 2 source produced
    it.
    """
    for entry in root.iterdir():
        if entry.name in IGNORED_DIR_NAMES:
            continue
        if entry.is_symlink():
            continue
        yield entry
        if entry.is_dir():
            yield from walk_workspace(entry)
