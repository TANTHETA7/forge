"""Repository import API router.

Purpose:       Expose repository import (ZIP upload, Git URL) and lookup over HTTP.
Responsibility: Translate between HTTP and application/repository_import/service.py
                only. This router is the one place that decides which concrete
                `RepositorySource` implementation to construct (ZIP vs. Git) based
                on which endpoint was called — the application layer only ever sees
                the `RepositorySource` port, never `ZipRepositorySource` or
                `GitRepositorySource` by name.

                The ZIP upload path streams the request body to a temp file with an
                independent byte-counted cap (`_save_upload_with_limit`) before
                `ZipRepositorySource` ever opens it — this is deliberately not the
                same check as `ZipRepositorySource.validate()`'s uncompressed-size
                cap; that one bounds what the archive *claims* to contain, this one
                bounds what the client actually sent over the wire.
Depends on:    application/repository_import/service.py, infrastructure/sources/*,
                infrastructure/workspace/*, infrastructure/scanner/*, api/schemas.py.
Depended on by: core/app_factory.py (registers this router).
"""

from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, UploadFile, status
from fastapi import File as UploadFileParam

from forge.api.schemas import GitImportRequest, RepositoryResponse
from forge.application.repository_import.service import RepositoryImportService
from forge.core.config import Settings, get_settings
from forge.domain.errors import UnsafeArchiveError
from forge.domain.project.ports import ProjectRepository
from forge.domain.repository.entities import Repository, RepositorySourceType
from forge.domain.repository.ports import RepositoryRepository
from forge.infrastructure.persistence.dependencies import (
    get_project_repository,
    get_repository_repository,
)
from forge.infrastructure.scanner.metadata_scanner import FilesystemMetadataScanner
from forge.infrastructure.sources.git_source import GitRepositorySource
from forge.infrastructure.sources.zip_source import ZipRepositorySource
from forge.infrastructure.workspace.workspace_manager import FilesystemWorkspaceProvider

router = APIRouter(prefix="/projects/{project_id}/repositories", tags=["repositories"])


def get_repository_import_service(
    projects: ProjectRepository = Depends(get_project_repository),
    repositories: RepositoryRepository = Depends(get_repository_repository),
    settings: Settings = Depends(get_settings),
) -> RepositoryImportService:
    return RepositoryImportService(
        projects=projects,
        repositories=repositories,
        workspaces=FilesystemWorkspaceProvider(settings),
        scanner=FilesystemMetadataScanner(),
    )


@router.post(
    "/import/zip", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED
)
async def import_zip_repository(
    project_id: UUID,
    file: UploadFile = UploadFileParam(...),
    display_name: str | None = Form(None),
    settings: Settings = Depends(get_settings),
    service: RepositoryImportService = Depends(get_repository_import_service),
) -> RepositoryResponse:
    """Import a repository from an uploaded ZIP archive."""
    archive_path = await _save_upload_with_limit(file, settings.max_upload_bytes)
    try:
        source = ZipRepositorySource(
            archive_path,
            max_total_size_bytes=settings.max_archive_uncompressed_bytes,
            max_file_count=settings.max_archive_file_count,
            max_single_file_bytes=settings.max_archive_single_file_bytes,
            max_compression_ratio=settings.max_archive_compression_ratio,
        )
        repository = await service.import_repository(
            project_id=project_id,
            source_type=RepositorySourceType.ZIP,
            source_ref=file.filename or "upload.zip",
            display_name=display_name or _stem(file.filename) or "Imported repository",
            source=source,
        )
    finally:
        archive_path.unlink(missing_ok=True)
    return RepositoryResponse(**_to_response_kwargs(repository))


@router.post(
    "/import/git", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED
)
async def import_git_repository(
    project_id: UUID,
    body: GitImportRequest,
    settings: Settings = Depends(get_settings),
    service: RepositoryImportService = Depends(get_repository_import_service),
) -> RepositoryResponse:
    """Import a repository from a public HTTPS git URL."""
    source = GitRepositorySource(
        body.url,
        clone_timeout_seconds=settings.git_clone_timeout_seconds,
        max_repo_size_bytes=settings.max_git_repo_size_bytes,
    )
    repository = await service.import_repository(
        project_id=project_id,
        source_type=RepositorySourceType.GIT,
        source_ref=body.url,
        display_name=_stem(body.url.rstrip("/")) or "Imported repository",
        source=source,
    )
    return RepositoryResponse(**_to_response_kwargs(repository))


@router.get("/{repository_id}", response_model=RepositoryResponse)
async def get_repository(
    project_id: UUID,
    repository_id: UUID,
    service: RepositoryImportService = Depends(get_repository_import_service),
) -> RepositoryResponse:
    """Fetch a repository's status/metadata by id."""
    repository = await service.get_repository(repository_id)
    return RepositoryResponse(**_to_response_kwargs(repository))


async def _save_upload_with_limit(file: UploadFile, max_bytes: int) -> Path:
    """Stream `file` to a new temp file, enforcing `max_bytes` as it's written —
    independent of any `Content-Length` header, which a client can lie about."""
    fd, tmp_name = tempfile.mkstemp(suffix=".zip")
    tmp_path = Path(tmp_name)
    written = 0
    try:
        with open(fd, "wb") as dest:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise UnsafeArchiveError(
                        f"Uploaded file exceeds the limit of {max_bytes} bytes"
                    )
                dest.write(chunk)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path


def _stem(name: str | None) -> str | None:
    if not name:
        return None
    return Path(name).stem or None


def _to_response_kwargs(repository: Repository) -> dict[str, Any]:
    """`asdict` handles the nested `RepositoryMetadata` dataclass automatically,
    so this maps 1:1 onto `RepositoryResponse`'s fields."""
    return asdict(repository)
