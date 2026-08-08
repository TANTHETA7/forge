"""Project application service.

Purpose:       Orchestrate project lifecycle use cases.
Responsibility: Two use cases today — create a project, look one up — with no HTTP
                or persistence mechanics of its own.
Depends on:    domain/project/entities.py, domain/project/ports.py, domain/errors.py.
Depended on by: api/projects.py, application/repository_import/service.py (indirectly,
                via the same ProjectRepository port, to confirm a project exists).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from forge.domain.errors import NotFoundError
from forge.domain.project.entities import Project, ProjectStatus
from forge.domain.project.ports import ProjectRepository


class ProjectService:
    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects

    async def create_project(self, name: str, description: str | None) -> Project:
        now = datetime.now(UTC)
        project = Project(
            id=uuid4(),
            name=name,
            description=description,
            status=ProjectStatus.CREATED,
            created_at=now,
            updated_at=now,
        )
        await self._projects.create(project)
        return project

    async def get_project(self, project_id: UUID) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        return project
