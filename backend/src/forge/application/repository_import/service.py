"""Repository import application service.

Purpose:       Orchestrate the Phase 2 workflow — validate a source, create an
                isolated workspace, materialize the source into it, scan metadata,
                and persist the result — for both ZIP and Git sources behind one
                code path.
Responsibility: Sequencing only. It never touches `zipfile`, `git`, or the
                filesystem directly — those are reached exclusively through the
                ports this class is constructed with (`domain/repository/ports.py`),
                which is what lets a future source type (`LocalRepositorySource`,
                `GitHubRepositorySource`, ...) plug in without changing this file.

                Blocking I/O (archive extraction, git clone, the filesystem walk)
                runs on a worker thread via `anyio.to_thread.run_sync` so it
                doesn't block the event loop that's also serving other requests —
                this keeps the import synchronous from the caller's point of view
                (no job-polling API in this phase) while staying a well-behaved
                ASGI citizen. See docs/architecture/02-engineering-specification.md
                §22 for why this is the deliberate extraction point if ingestion
                ever needs to move to a queue-backed worker.
Depends on:    domain/repository/ports.py, domain/project/ports.py, domain/errors.py, anyio.
Depended on by: api/repositories.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import anyio.to_thread

from forge.domain.errors import NotFoundError, SourceImportError, SourceValidationError
from forge.domain.project.ports import ProjectRepository
from forge.domain.repository.entities import (
    Repository,
    RepositorySourceType,
    RepositoryStatus,
)
from forge.domain.repository.ports import (
    MetadataScanner,
    RepositoryRepository,
    RepositorySource,
    WorkspaceProvider,
)


class RepositoryImportService:
    def __init__(
        self,
        projects: ProjectRepository,
        repositories: RepositoryRepository,
        workspaces: WorkspaceProvider,
        scanner: MetadataScanner,
    ) -> None:
        self._projects = projects
        self._repositories = repositories
        self._workspaces = workspaces
        self._scanner = scanner

    async def import_repository(
        self,
        *,
        project_id: UUID,
        source_type: RepositorySourceType,
        source_ref: str,
        display_name: str,
        source: RepositorySource,
    ) -> Repository:
        """Run the full import workflow and return the resulting `Repository`.

        Raises:
            NotFoundError: `project_id` doesn't exist — nothing is touched on disk.
            SourceValidationError: the source failed validation — nothing is
                touched on disk (validation always runs before workspace creation).
            SourceImportError: validation passed but materialization or scanning
                failed — the repository is persisted with `status=FAILED` and its
                workspace is removed before this is raised.
        """
        if await self._projects.get_by_id(project_id) is None:
            raise NotFoundError(f"Project {project_id} not found")

        # Validate before anything touches disk — a rejected source leaves no trace.
        await anyio.to_thread.run_sync(source.validate)

        now = datetime.now(UTC)
        repository_id = uuid4()
        workspace = await anyio.to_thread.run_sync(
            self._workspaces.create_workspace, project_id, repository_id
        )
        repository = Repository(
            id=repository_id,
            project_id=project_id,
            source_type=source_type,
            source_ref=source_ref,
            display_name=display_name,
            workspace_path=str(workspace),
            status=RepositoryStatus.IMPORTING,
            metadata=None,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
        await self._repositories.create(repository)

        try:
            await anyio.to_thread.run_sync(source.materialize_into, workspace)
            metadata = await anyio.to_thread.run_sync(self._scanner.scan, workspace)
        except Exception as exc:
            failed_at = datetime.now(UTC)
            repository = repository.with_status(
                RepositoryStatus.FAILED, updated_at=failed_at, error_message=str(exc)
            )
            await self._repositories.update(repository)
            await anyio.to_thread.run_sync(self._workspaces.delete_workspace, workspace)
            if isinstance(exc, (SourceImportError, SourceValidationError)):
                raise
            raise SourceImportError(
                f"Unexpected failure while importing repository: {exc}"
            ) from exc

        ready_at = datetime.now(UTC)
        repository = repository.with_metadata(metadata, updated_at=ready_at).with_status(
            RepositoryStatus.READY, updated_at=ready_at
        )
        await self._repositories.update(repository)
        return repository

    async def get_repository(self, repository_id: UUID) -> Repository:
        repository = await self._repositories.get_by_id(repository_id)
        if repository is None:
            raise NotFoundError(f"Repository {repository_id} not found")
        return repository
