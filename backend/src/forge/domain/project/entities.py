"""Project domain model.

Purpose:       Define what a Forge "project" is, independent of HTTP or persistence.
Responsibility: A single entity, `Project`, plus the states it can be in. A project is
                the top-level container a user creates before importing a repository
                into it (see `domain/repository/entities.py`).
Depends on:    stdlib only.
Depended on by: application/project/service.py, application/repository_import/service.py,
                infrastructure/persistence/project_repository_impl.py.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ProjectStatus(StrEnum):
    """Lifecycle state of a `Project`."""

    CREATED = "created"
    IMPORTING = "importing"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Project:
    """An immutable snapshot of a Forge project.

    Attributes:
        id: Server-generated identifier — never derived from user input, which is
            part of what makes workspace paths built from it safe (see
            `infrastructure/workspace/workspace_manager.py`).
        name: Display name, chosen by the user.
        description: Optional free-text description.
        status: Current lifecycle state.
        created_at: Creation timestamp (UTC).
        updated_at: Last-modified timestamp (UTC).
    """

    id: UUID
    name: str
    description: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime

    def with_status(self, status: ProjectStatus, *, updated_at: datetime) -> Project:
        """Return a copy of this project with a new status. Never mutates `self` —
        callers persist the returned copy."""
        return replace(self, status=status, updated_at=updated_at)
