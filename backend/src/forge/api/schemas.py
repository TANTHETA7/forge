"""Shared API-layer response schemas.

Purpose:       Pydantic models that define the HTTP contract, kept separate from
                domain models so a domain change doesn't silently change the wire
                format (and vice versa).
Responsibility: Serialization shape only — no behavior.
Depends on:    pydantic.
Depended on by: api/health.py, and every future router.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Wire format for `GET /health`."""

    state: str = Field(..., examples=["ok"])
    app_name: str = Field(..., examples=["Forge"])
    version: str = Field(..., examples=["0.1.0"])


class ErrorResponse(BaseModel):
    """Wire format for every error response — see api/error_handlers.py."""

    error: str = Field(..., examples=["not_found"])
    message: str


class ProjectCreateRequest(BaseModel):
    """Wire format for `POST /projects`."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)


class ProjectResponse(BaseModel):
    """Wire format for a `Project`."""

    id: UUID
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class RepositoryMetadataResponse(BaseModel):
    """Wire format for `RepositoryMetadata`."""

    file_count: int
    directory_count: int
    total_size_bytes: int
    language_stats: dict[str, float]
    has_readme: bool
    has_git: bool
    scanned_at: datetime


class RepositoryResponse(BaseModel):
    """Wire format for a `Repository`."""

    id: UUID
    project_id: UUID
    source_type: str
    display_name: str
    status: str
    metadata: RepositoryMetadataResponse | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class GitImportRequest(BaseModel):
    """Wire format for `POST /projects/{id}/repositories/import/git`."""

    url: str = Field(..., min_length=1, max_length=2000, examples=["https://github.com/org/repo.git"])
