"""Repository domain model — one imported repository within a project.

Purpose:       Define what an "imported repository" is, independent of HTTP,
                persistence, or which source type (ZIP, Git, ...) produced it.
Responsibility: The `Repository` entity, its lifecycle states, its source-type tag,
                and the immutable `RepositoryMetadata` value object the metadata
                scanner produces.
Depends on:    stdlib only.
Depended on by: application/repository_import/service.py,
                infrastructure/persistence/repository_repository_impl.py,
                infrastructure/scanner/metadata_scanner.py (return type only).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class RepositorySourceType(StrEnum):
    """Which kind of `RepositorySource` (domain/repository/ports.py) produced this
    repository. New source types (LOCAL, GITHUB, ...) are added here as they're
    implemented — see docs/architecture/02-engineering-specification.md §24."""

    ZIP = "zip"
    GIT = "git"


class RepositoryStatus(StrEnum):
    """Lifecycle state of an imported repository."""

    PENDING = "pending"
    IMPORTING = "importing"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RepositoryMetadata:
    """Structural summary produced by the metadata scanner after a successful import.

    Attributes:
        file_count: Number of files (directories and ignored paths excluded).
        directory_count: Number of directories.
        total_size_bytes: Sum of file sizes on disk, in bytes.
        language_stats: Language name -> percentage of files (0-100, need not sum
            to exactly 100 since files with unrecognized extensions are excluded).
        has_readme: Whether a `README*` file exists at any level.
        has_git: Whether a `.git` directory exists at the workspace root.
        scanned_at: When this scan ran (UTC).
    """

    file_count: int
    directory_count: int
    total_size_bytes: int
    language_stats: dict[str, float]
    has_readme: bool
    has_git: bool
    scanned_at: datetime


@dataclass(frozen=True, slots=True)
class Repository:
    """An immutable snapshot of one imported repository.

    Attributes:
        id: Server-generated identifier — also the workspace directory's leaf
            component (see `infrastructure/workspace/workspace_manager.py`).
        project_id: The owning `Project`'s id.
        source_type: Which kind of source this came from.
        source_ref: Opaque, display-only reference to the original source — the
            uploaded filename for ZIP, the credential-free URL for Git. Never used
            to derive a filesystem path.
        display_name: Human-readable name shown in the UI.
        workspace_path: Absolute path to this repository's isolated workspace.
        status: Current lifecycle state.
        metadata: Populated once the repository reaches `READY`; `None` until then.
        error_message: Populated once the repository reaches `FAILED`; `None`
            otherwise.
        created_at: Creation timestamp (UTC).
        updated_at: Last-modified timestamp (UTC).
    """

    id: UUID
    project_id: UUID
    source_type: RepositorySourceType
    source_ref: str
    display_name: str
    workspace_path: str
    status: RepositoryStatus
    metadata: RepositoryMetadata | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    def with_status(
        self,
        status: RepositoryStatus,
        *,
        updated_at: datetime,
        error_message: str | None = None,
    ) -> Repository:
        """Return a copy with a new status. Never mutates `self`."""
        return replace(self, status=status, error_message=error_message, updated_at=updated_at)

    def with_metadata(self, metadata: RepositoryMetadata, *, updated_at: datetime) -> Repository:
        """Return a copy with scan results attached. Never mutates `self`."""
        return replace(self, metadata=metadata, updated_at=updated_at)
