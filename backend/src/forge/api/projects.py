"""Project API router.

Purpose:       Expose project creation/lookup over HTTP.
Responsibility: Translate between HTTP and application/project/service.py only — no
                business logic lives here.
Depends on:    application/project/service.py, api/schemas.py,
                infrastructure/persistence/dependencies.py.
Depended on by: core/app_factory.py (registers this router).
"""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, status

from forge.api.schemas import ProjectCreateRequest, ProjectResponse
from forge.application.project.service import ProjectService
from forge.domain.project.ports import ProjectRepository
from forge.infrastructure.persistence.dependencies import get_project_repository

router = APIRouter(prefix="/projects", tags=["projects"])


def get_project_service(
    projects: ProjectRepository = Depends(get_project_repository),
) -> ProjectService:
    return ProjectService(projects)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreateRequest, service: ProjectService = Depends(get_project_service)
) -> ProjectResponse:
    """Create a new Forge project."""
    project = await service.create_project(body.name, body.description)
    return ProjectResponse(**asdict(project))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID, service: ProjectService = Depends(get_project_service)
) -> ProjectResponse:
    """Fetch a project by id. 404s via api/error_handlers.py if it doesn't exist."""
    project = await service.get_project(project_id)
    return ProjectResponse(**asdict(project))
