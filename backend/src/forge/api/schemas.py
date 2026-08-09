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


class ParameterResponse(BaseModel):
    """Wire format for a `Parameter`."""

    name: str
    position: int
    annotation: str | None
    default_value: str | None


class SymbolResponse(BaseModel):
    """Wire format for a `Symbol`."""

    id: UUID
    kind: str
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    start_column: int | None
    end_column: int | None
    parameters: list[ParameterResponse]
    parent_symbol_id: UUID | None


class ImportResponse(BaseModel):
    """Wire format for an `Import`."""

    id: UUID
    module: str
    imported_names: list[str]
    alias: str | None
    start_line: int
    end_line: int


class ParsedFileResponse(BaseModel):
    """Wire format for `GET .../files` — a per-file summary, not the full symbol/
    import list (see `GET .../symbols` for that)."""

    id: UUID
    repository_id: UUID
    path: str
    language: str
    has_syntax_errors: bool
    symbol_count: int
    import_count: int


class ParseErrorResponse(BaseModel):
    """Wire format for one recorded parse failure."""

    file_path: str
    stage: str
    message: str


class ParseSummaryResponse(BaseModel):
    """Wire format for `POST .../parse`."""

    repository_id: UUID
    file_count: int
    symbol_count: int
    import_count: int
    error_count: int
    parsed_at: datetime
