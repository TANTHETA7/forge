"""File discovery — the only component that touches raw workspace paths.

Purpose:       Walk an already-materialized repository workspace and yield, per
                file, either its content (ready to hand to a `LanguageParser`) or
                why it was excluded — without deciding language support, which is
                `ParserRegistry`'s job (called per candidate by
                `application/parsing/service.py`, not here).
Responsibility: Filesystem I/O and two policy decisions: skip binary-looking
                files, skip files over a configured size cap. Both are silent
                skips (`stage=None`) — not failures, deliberate exclusions.
                Anything that fails to even `stat()`/read is a real failure
                (`stage="read"`), reported so it can be recorded as a
                `ParseError` by the caller.
Depends on:    infrastructure/filesystem/workspace_walker.py,
                domain/parsing/entities.py, domain/parsing/ports.py.
Depended on by: application/parsing/service.py, via
                domain/parsing/ports.py::FileDiscovery.

Security note: `discover` takes whatever `Path` its caller passes — it never
resolves a path from client input itself. The one and only legitimate caller,
`application/parsing/service.py`, always passes `Repository.workspace_path`
(domain/repository/entities.py), which is set exactly once, by Phase 2's
`WorkspaceProvider`, from server-generated UUIDs — never from a project/
repository name or any other client-controlled value. This module doesn't
re-derive that guarantee; it relies on it, the same way
`infrastructure/scanner/metadata_scanner.py` already does.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from forge.domain.parsing.entities import DiscoveredFile, SkippedFile
from forge.infrastructure.filesystem.workspace_walker import walk_workspace

# Sniffing the first few KB for a null byte is the same heuristic git itself uses
# to decide "binary" vs "text" — cheap, no extra dependency, right almost always.
_BINARY_SNIFF_BYTES = 8192


class FilesystemFileDiscovery:
    """A `FileDiscovery` (domain/parsing/ports.py) that walks a real workspace
    directory."""

    def __init__(self, *, max_file_bytes: int) -> None:
        self._max_file_bytes = max_file_bytes

    def discover(self, workspace: Path) -> Iterator[DiscoveredFile | SkippedFile]:
        root = workspace.resolve()
        for entry in walk_workspace(root):
            if entry.is_dir():
                continue

            relative_path = entry.relative_to(root).as_posix()

            try:
                size = entry.stat().st_size
            except OSError as exc:
                yield SkippedFile(relative_path, f"could not stat file: {exc}", stage="read")
                continue

            if size > self._max_file_bytes:
                yield SkippedFile(
                    relative_path,
                    f"file is {size} bytes, exceeding the {self._max_file_bytes}-byte limit",
                )
                continue

            try:
                content = entry.read_bytes()
            except OSError as exc:
                yield SkippedFile(relative_path, f"could not read file: {exc}", stage="read")
                continue

            if _looks_binary(content):
                yield SkippedFile(relative_path, "file appears to be binary")
                continue

            yield DiscoveredFile(relative_path=relative_path, content=content)


def _looks_binary(content: bytes) -> bool:
    """A null byte in the first `_BINARY_SNIFF_BYTES` — the same heuristic git
    itself uses to classify a file as binary."""
    return b"\x00" in content[:_BINARY_SNIFF_BYTES]
