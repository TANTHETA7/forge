"""In-memory fakes for the Phase 2 persistence ports.

Purpose: Let unit/integration tests exercise application services and API routes
against real port contracts (`ProjectRepository`, `RepositoryRepository`) without a
live Postgres — this environment has no Docker available to run one (matching
Phase 1's disclosed docker-compose limitation). A live-Postgres contract test for
the SQLAlchemy implementations is the natural next addition once Postgres is
reachable in CI/dev, per docs/architecture/02-engineering-specification.md §20.
"""

from __future__ import annotations

from uuid import UUID

from forge.domain.project.entities import Project
from forge.domain.repository.entities import Repository


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[UUID, Project] = {}

    async def create(self, project: Project) -> None:
        self._projects[project.id] = project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return self._projects.get(project_id)

    async def update(self, project: Project) -> None:
        self._projects[project.id] = project


class InMemoryRepositoryRepository:
    def __init__(self) -> None:
        self._repositories: dict[UUID, Repository] = {}

    async def create(self, repository: Repository) -> None:
        self._repositories[repository.id] = repository

    async def get_by_id(self, repository_id: UUID) -> Repository | None:
        return self._repositories.get(repository_id)

    async def update(self, repository: Repository) -> None:
        self._repositories[repository.id] = repository
