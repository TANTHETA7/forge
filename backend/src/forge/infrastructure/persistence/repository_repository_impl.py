"""SQLAlchemy implementation of `domain/repository/ports.py::RepositoryRepository`.

Purpose:       Persist and retrieve `Repository` entities (and their attached
                `RepositoryMetadata`) in Postgres.
Responsibility: Translate between the domain entity and the ORM row
                (models.py::RepositoryRow) only — no business logic.
Depends on:    sqlalchemy, domain/repository/entities.py, infrastructure/persistence/models.py.
Depended on by: infrastructure/persistence/dependencies.py.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.repository.entities import (
    Repository,
    RepositoryMetadata,
    RepositorySourceType,
    RepositoryStatus,
)
from forge.infrastructure.persistence.models import RepositoryRow


class SqlAlchemyRepositoryRepository:
    """A `RepositoryRepository` backed by Postgres via SQLAlchemy's async engine."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, repository: Repository) -> None:
        self._session.add(_to_row(repository))
        await self._session.commit()

    async def get_by_id(self, repository_id: UUID) -> Repository | None:
        row = await self._session.get(RepositoryRow, repository_id)
        return _to_entity(row) if row is not None else None

    async def update(self, repository: Repository) -> None:
        row = await self._session.get(RepositoryRow, repository.id)
        if row is None:
            return
        row.status = repository.status.value
        row.error_message = repository.error_message
        row.updated_at = repository.updated_at
        _apply_metadata(row, repository.metadata)
        await self._session.commit()


def _to_row(repository: Repository) -> RepositoryRow:
    row = RepositoryRow(
        id=repository.id,
        project_id=repository.project_id,
        source_type=repository.source_type.value,
        source_ref=repository.source_ref,
        display_name=repository.display_name,
        workspace_path=repository.workspace_path,
        status=repository.status.value,
        error_message=repository.error_message,
        created_at=repository.created_at,
        updated_at=repository.updated_at,
    )
    _apply_metadata(row, repository.metadata)
    return row


def _apply_metadata(row: RepositoryRow, metadata: RepositoryMetadata | None) -> None:
    if metadata is None:
        return
    row.meta_file_count = metadata.file_count
    row.meta_directory_count = metadata.directory_count
    row.meta_total_size_bytes = metadata.total_size_bytes
    row.meta_language_stats = metadata.language_stats
    row.meta_has_readme = metadata.has_readme
    row.meta_has_git = metadata.has_git
    row.meta_scanned_at = metadata.scanned_at


def _to_entity(row: RepositoryRow) -> Repository:
    return Repository(
        id=row.id,
        project_id=row.project_id,
        source_type=RepositorySourceType(row.source_type),
        source_ref=row.source_ref,
        display_name=row.display_name,
        workspace_path=row.workspace_path,
        status=RepositoryStatus(row.status),
        metadata=_extract_metadata(row),
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _extract_metadata(row: RepositoryRow) -> RepositoryMetadata | None:
    if row.meta_scanned_at is None:
        return None
    assert row.meta_file_count is not None
    assert row.meta_directory_count is not None
    assert row.meta_total_size_bytes is not None
    assert row.meta_has_readme is not None
    assert row.meta_has_git is not None
    return RepositoryMetadata(
        file_count=row.meta_file_count,
        directory_count=row.meta_directory_count,
        total_size_bytes=row.meta_total_size_bytes,
        language_stats=row.meta_language_stats or {},
        has_readme=row.meta_has_readme,
        has_git=row.meta_has_git,
        scanned_at=row.meta_scanned_at,
    )
