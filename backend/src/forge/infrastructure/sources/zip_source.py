"""ZIP archive repository source, hardened against malicious archives.

Purpose:       Materialize an uploaded ZIP archive into a workspace directory.
Responsibility: Validate and extract a ZIP archive. This is the one place in Forge
                that turns untrusted, user-uploaded bytes into files on disk — every
                check below exists because skipping it is a known, exploitable
                vulnerability class:

                - **Path traversal / "Zip Slip"**: an entry named e.g.
                  `../../etc/cron.d/evil` that, naively extracted, writes outside the
                  target directory. Defended twice — once by rejecting suspicious
                  names outright (`_validate_entry_name`), once by refusing to
                  extract to any resolved path outside the workspace regardless of
                  what the name looked like (`_resolve_entry_path`) — because the
                  first check is a name-shape heuristic and the second is the actual
                  invariant; never rely on only one.
                - **Absolute paths / drive letters / UNC paths**: entries that
                  bypass the "relative to workspace" assumption entirely.
                - **Symlink entries**: a ZIP can encode a symlink whose target
                  escapes the workspace *after* extraction, when something later
                  reads through it. Rejected outright — Forge never extracts a
                  symlink.
                - **Zip bombs**: a small archive that claims (or, with a forged
                  central directory, actually produces) a huge amount of data.
                  Guarded by a total-uncompressed-size cap, a per-file cap, a
                  compression-ratio heuristic, AND an independent byte-counted
                  stream copy at extraction time that doesn't trust the central
                  directory's claimed sizes.
                - **Entry-count exhaustion**: an archive with millions of
                  zero-byte entries. Capped independently of total size.
Depends on:    zipfile (stdlib), domain/errors.py.
Depended on by: api/repositories.py (constructs this); called only through
                domain/repository/ports.py::RepositorySource by
                application/repository_import/service.py.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path
from typing import IO

from forge.domain.errors import SourceImportError, UnsafeArchiveError

_CHUNK_SIZE = 1024 * 1024


class ZipRepositorySource:
    """A `RepositorySource` backed by a ZIP archive already on local disk (the API
    layer is responsible for streaming an upload to disk with its own size cap
    before constructing this — see `api/repositories.py`)."""

    def __init__(
        self,
        archive_path: Path,
        *,
        max_total_size_bytes: int,
        max_file_count: int,
        max_single_file_bytes: int,
        max_compression_ratio: int,
    ) -> None:
        self._archive_path = archive_path
        self._max_total_size_bytes = max_total_size_bytes
        self._max_file_count = max_file_count
        self._max_single_file_bytes = max_single_file_bytes
        self._max_compression_ratio = max_compression_ratio

    def validate(self) -> None:
        try:
            with zipfile.ZipFile(self._archive_path) as archive:
                infos = archive.infolist()
        except zipfile.BadZipFile as exc:
            raise UnsafeArchiveError("File is not a valid ZIP archive") from exc

        if len(infos) == 0:
            raise UnsafeArchiveError("Archive contains no entries")
        if len(infos) > self._max_file_count:
            raise UnsafeArchiveError(
                f"Archive contains {len(infos)} entries, exceeding the limit of "
                f"{self._max_file_count}"
            )

        total_uncompressed = 0
        for info in infos:
            _validate_entry_name(info.filename)
            _reject_symlink(info)

            if info.file_size > self._max_single_file_bytes:
                raise UnsafeArchiveError(
                    f"Entry {info.filename!r} is {info.file_size} bytes, exceeding "
                    f"the per-file limit of {self._max_single_file_bytes}"
                )
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > self._max_compression_ratio:
                    raise UnsafeArchiveError(
                        f"Entry {info.filename!r} has a suspicious compression "
                        f"ratio ({ratio:.0f}:1)"
                    )
            total_uncompressed += info.file_size

        if total_uncompressed > self._max_total_size_bytes:
            raise UnsafeArchiveError(
                f"Archive would extract to {total_uncompressed} bytes, exceeding "
                f"the limit of {self._max_total_size_bytes}"
            )

    def materialize_into(self, workspace: Path) -> None:
        workspace = workspace.resolve()
        try:
            with zipfile.ZipFile(self._archive_path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        _resolve_entry_path(workspace, info.filename).mkdir(
                            parents=True, exist_ok=True
                        )
                        continue
                    target = _resolve_entry_path(workspace, info.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as dest:
                        _copy_with_limit(source, dest, self._max_single_file_bytes)
        except zipfile.BadZipFile as exc:
            raise SourceImportError("Archive became unreadable during extraction") from exc


def _reject_symlink(info: zipfile.ZipInfo) -> None:
    """Unix ZIP entries encode file mode in the upper 16 bits of `external_attr`;
    reject anything flagged as a symlink there before it's ever extracted."""
    unix_mode = info.external_attr >> 16
    if unix_mode and stat.S_ISLNK(unix_mode):
        raise UnsafeArchiveError(
            f"Archive entry is a symlink, which Forge refuses: {info.filename!r}"
        )


def _validate_entry_name(name: str) -> None:
    """Reject any entry name that isn't a safe, relative path — a name-shape
    check that runs before any bytes are written. See `_resolve_entry_path` for
    the independent, authoritative check enforced at extraction time."""
    if not name or name.strip() in {"", ".", "/"}:
        raise UnsafeArchiveError("Archive contains an empty entry name")
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        raise UnsafeArchiveError(f"Archive entry has an absolute path: {name!r}")
    first_segment = normalized.split("/", 1)[0]
    if ":" in first_segment:
        # Windows drive letter (`C:...`) or an alternate-data-stream style name.
        raise UnsafeArchiveError(f"Archive entry has an unsafe path: {name!r}")
    if ".." in normalized.split("/"):
        raise UnsafeArchiveError(f"Archive entry escapes the archive root: {name!r}")


def _resolve_entry_path(workspace: Path, name: str) -> Path:
    """Resolve an archive entry name against `workspace` and refuse to return a
    path outside it. This — not `_validate_entry_name` — is the actual Zip Slip
    defense: it's checked against the resolved filesystem path, independent of
    what the entry name looked like."""
    candidate = (workspace / name).resolve()
    if not candidate.is_relative_to(workspace):
        raise UnsafeArchiveError(f"Archive entry resolves outside the workspace: {name!r}")
    return candidate


def _copy_with_limit(source: IO[bytes], dest: IO[bytes], max_bytes: int) -> None:
    """Stream-copy with a hard byte cap, so a forged size in the ZIP's central
    directory (which `validate()` otherwise trusts) can't cause an unbounded write
    during extraction."""
    written = 0
    while True:
        chunk = source.read(_CHUNK_SIZE)
        if not chunk:
            break
        written += len(chunk)
        if written > max_bytes:
            raise UnsafeArchiveError("Entry exceeded its declared size during extraction")
        dest.write(chunk)
