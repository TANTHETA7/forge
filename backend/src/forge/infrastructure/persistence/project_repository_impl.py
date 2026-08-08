"""SQLAlchemy implementation of `domain/project/ports.py::ProjectRepository`.

Purpose:       Persist and retrieve `Project` entities in Postgres.
Responsibility: Translate between the domain entity and the ORM row
                (models.py::ProjectRow) only — no business logic.
Depends on:    sqlalchemy, domain/project/entities.py, infrastructure/persistence/models.py.
Depended on by: infrastructure/persistence/dependencies.py.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.project.entities import Project, ProjectStatus
from forge.infrastructure.persistence.models import ProjectRow


class SqlAlchemyProjectRepository:
    """A `ProjectRepository` backed by Postgres via SQLAlchemy's async engine."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, project: Project) -> None:
        self._session.add(_to_row(project))
        await self._session.commit()

    async def get_by_id(self, project_id: UUID) -> Project | None:
        row = await self._session.get(ProjectRow, project_id)
        return _to_entity(row) if row is not None else None

    async def update(self, project: Project) -> None:
        row = await self._session.get(ProjectRow, project.id)
        if row is None:
            return
        row.name = project.name
        row.description = project.description
        row.status = project.status.value
        row.updated_at = project.updated_at
        await self._session.commit()


def _to_row(project: Project) -> ProjectRow:
    return ProjectRow(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status.value,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _to_entity(row: ProjectRow) -> Project:
    return Project(
        id=row.id,
        name=row.name,
        description=row.description,
        status=ProjectStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
