"""Persistence port for `Project` aggregates.

Purpose:       Let the application layer create/read/update projects without knowing
                whether they live in Postgres, SQLite, or memory.
Responsibility: Interface only — no implementation. Implemented by
                infrastructure/persistence/project_repository_impl.py.
Depends on:    domain/project/entities.py.
Depended on by: application/project/service.py, application/repository_import/service.py.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from forge.domain.project.entities import Project


class ProjectRepository(Protocol):
    """Persistence port for `Project`. "Repository" here is the persistence-pattern
    sense of the word (a collection-like gateway to storage) — unrelated to a git
    repository, which is `domain/repository/entities.py::Repository`."""

    async def create(self, project: Project) -> None: ...

    async def get_by_id(self, project_id: UUID) -> Project | None: ...

    async def update(self, project: Project) -> None: ...
