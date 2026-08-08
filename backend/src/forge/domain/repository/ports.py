"""Ports the repository-import workflow depends on, each implemented by
infrastructure and injected into `application/repository_import/service.py`.

Purpose:       Let the application layer validate, materialize, scan, and persist a
                repository without importing `zipfile`, `git`, or `pathlib`
                filesystem operations directly — the actual mechanism for the rule
                "the application layer must not depend on filesystem APIs, ZIP
                implementation details, Git command execution, or HTTP clients"
                stated in docs/architecture/02-engineering-specification.md.
Responsibility: Interfaces only — no implementation.
Depends on:    domain/repository/entities.py.
Depended on by: application/repository_import/service.py; implemented by
                infrastructure/sources/*.py, infrastructure/workspace/*.py,
                infrastructure/scanner/*.py, infrastructure/persistence/*.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from forge.domain.repository.entities import Repository, RepositoryMetadata


class RepositorySource(Protocol):
    """A not-yet-materialized repository source — a ZIP upload or a git URL.

    Implementations must never partially populate a workspace and report success:
    `materialize_into` either fully succeeds or raises, leaving cleanup to the
    caller (the caller owns workspace lifecycle, not the source).
    """

    def validate(self) -> None:
        """Raise a `SourceValidationError` subtype (see domain/errors.py) if this
        source is unsafe or malformed. Must be called, and must succeed, before
        `materialize_into` — validation never touches the workspace."""
        ...

    def materialize_into(self, workspace: Path) -> None:
        """Populate `workspace` (already created and empty) with the source's files.
        Raises `SourceImportError` on failure."""
        ...


class WorkspaceProvider(Protocol):
    """Creates and removes the isolated, per-repository directory a source is
    materialized into. See `infrastructure/workspace/workspace_manager.py` for why
    every path this returns is safe by construction."""

    def create_workspace(self, project_id: UUID, repository_id: UUID) -> Path: ...

    def delete_workspace(self, workspace: Path) -> None: ...


class MetadataScanner(Protocol):
    """Produces a `RepositoryMetadata` summary from an already-materialized
    workspace. Never reads file contents beyond what's needed for the summary —
    that's the future Parsing Engine's job, not this one's."""

    def scan(self, workspace: Path) -> RepositoryMetadata: ...


class RepositoryRepository(Protocol):
    """Persistence port for `Repository`."""

    async def create(self, repository: Repository) -> None: ...

    async def get_by_id(self, repository_id: UUID) -> Repository | None: ...

    async def update(self, repository: Repository) -> None: ...
