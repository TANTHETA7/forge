"""Filesystem source reader (Phase 7).

Purpose:       Read a parsed file's current text back out of its repository's
                isolated workspace, so the chunker has real source to carve —
                the source text is not stored in Postgres (only structure is),
                so indexing reads it from disk on demand.
Responsibility: One `SourceReader` implementation. Path confinement, size
                bounding, and text-decoding only — no chunking, no parsing.

Security posture mirrors the rest of the workspace handling (see
infrastructure/workspace/): the joined path is resolved and verified to stay
*inside* the resolved workspace root before any read, so a crafted
`relative_path` (`../../etc/passwd`, an absolute path, a symlink escaping the
workspace) can never read a file outside the repository's own workspace. Any
failure — missing file, too large, outside the root, undecodable bytes — returns
`None` rather than raising, so a single unreadable file never aborts a whole
index run (the indexing service records it as skipped and moves on).

Depends on:    domain/rag/ports.py (structural), stdlib pathlib.
Depended on by: infrastructure/rag/dependencies.py.
"""

from __future__ import annotations

from pathlib import Path


class FilesystemSourceReader:
    """A `SourceReader` that reads text files from within a workspace root.

    Args:
        max_bytes: Files larger than this are skipped (returned as `None`).
            Defaults align with parsing's own per-file ceiling so a file that was
            parseable is readable here too.
    """

    def __init__(self, *, max_bytes: int) -> None:
        self._max_bytes = max_bytes

    def read_text(self, workspace_path: str, relative_path: str) -> str | None:
        """Return the UTF-8 text of `relative_path` under `workspace_path`, or
        `None` if it is missing, too large, outside the workspace, or not
        decodable as UTF-8 text."""
        try:
            root = Path(workspace_path).resolve()
            target = (root / relative_path).resolve()
        except (OSError, ValueError):
            # A path too long, containing NUL bytes, or otherwise un-resolvable.
            return None

        # Confinement: the resolved target must be the root itself or beneath it.
        if root != target and root not in target.parents:
            return None

        try:
            if not target.is_file():
                return None
            if target.stat().st_size > self._max_bytes:
                return None
            data = target.read_bytes()
        except OSError:
            return None

        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None
