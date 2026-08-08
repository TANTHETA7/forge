"""Orchestration tests for RepositoryImportService.

Exercises the full workflow — project lookup, validate, workspace creation,
materialize, scan, persist — against real infrastructure (a real ZIP archive, a
real filesystem workspace, the real metadata scanner) but in-memory fakes for
persistence (see tests/fakes.py), so it proves the actual wiring without needing
Postgres.
"""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from forge.application.repository_import.service import RepositoryImportService
from forge.core.config import Settings
from forge.domain.errors import NotFoundError, SourceImportError, SourceValidationError
from forge.domain.project.entities import Project, ProjectStatus
from forge.domain.repository.entities import RepositorySourceType, RepositoryStatus
from forge.infrastructure.scanner.metadata_scanner import FilesystemMetadataScanner
from forge.infrastructure.sources.zip_source import ZipRepositorySource
from forge.infrastructure.workspace.workspace_manager import FilesystemWorkspaceProvider
from tests.fakes import InMemoryProjectRepository, InMemoryRepositoryRepository


def _make_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("README.md", "hello forge")
        zf.writestr("src/main.py", "print('hi')\n")
    return path


async def _seed_project(projects: InMemoryProjectRepository) -> Project:
    now = datetime.now(UTC)
    project = Project(
        id=uuid4(),
        name="Test project",
        description=None,
        status=ProjectStatus.CREATED,
        created_at=now,
        updated_at=now,
    )
    await projects.create(project)
    return project


_Ports = tuple[RepositoryImportService, InMemoryProjectRepository, InMemoryRepositoryRepository]


def _service(tmp_path: Path) -> _Ports:
    settings = Settings(workspace_root_dir=str(tmp_path / "workspaces"))
    projects = InMemoryProjectRepository()
    repositories = InMemoryRepositoryRepository()
    service = RepositoryImportService(
        projects=projects,
        repositories=repositories,
        workspaces=FilesystemWorkspaceProvider(settings),
        scanner=FilesystemMetadataScanner(),
    )
    return service, projects, repositories


async def test_successful_zip_import_reaches_ready(tmp_path: Path) -> None:
    service, projects, _repositories = _service(tmp_path)
    project = await _seed_project(projects)
    archive_path = _make_zip(tmp_path / "upload.zip")
    source = ZipRepositorySource(
        archive_path,
        max_total_size_bytes=10 * 1024 * 1024,
        max_file_count=100,
        max_single_file_bytes=1024 * 1024,
        max_compression_ratio=100,
    )

    repository = await service.import_repository(
        project_id=project.id,
        source_type=RepositorySourceType.ZIP,
        source_ref="upload.zip",
        display_name="upload",
        source=source,
    )

    assert repository.status == RepositoryStatus.READY
    assert repository.metadata is not None
    assert repository.metadata.file_count == 2
    assert repository.metadata.has_readme is True
    assert Path(repository.workspace_path).exists()
    assert (Path(repository.workspace_path) / "README.md").read_text() == "hello forge"


async def test_import_into_unknown_project_raises_not_found(tmp_path: Path) -> None:
    service, _projects, _repositories = _service(tmp_path)
    archive_path = _make_zip(tmp_path / "upload.zip")
    source = ZipRepositorySource(
        archive_path,
        max_total_size_bytes=10 * 1024 * 1024,
        max_file_count=100,
        max_single_file_bytes=1024 * 1024,
        max_compression_ratio=100,
    )

    with pytest.raises(NotFoundError):
        await service.import_repository(
            project_id=uuid4(),
            source_type=RepositorySourceType.ZIP,
            source_ref="upload.zip",
            display_name="upload",
            source=source,
        )


async def test_invalid_archive_is_rejected_before_any_workspace_is_created(
    tmp_path: Path,
) -> None:
    service, projects, repositories = _service(tmp_path)
    project = await _seed_project(projects)
    bad_archive = tmp_path / "bad.zip"
    bad_archive.write_bytes(b"not a zip")
    source = ZipRepositorySource(
        bad_archive,
        max_total_size_bytes=10 * 1024 * 1024,
        max_file_count=100,
        max_single_file_bytes=1024 * 1024,
        max_compression_ratio=100,
    )

    with pytest.raises(SourceValidationError):
        await service.import_repository(
            project_id=project.id,
            source_type=RepositorySourceType.ZIP,
            source_ref="bad.zip",
            display_name="bad",
            source=source,
        )

    assert repositories._repositories == {}  # noqa: SLF001 — asserting no side effect


class _FailingSource:
    def validate(self) -> None:
        pass

    def materialize_into(self, workspace: Path) -> None:
        raise SourceImportError("simulated clone failure")


async def test_materialize_failure_marks_repository_failed_and_removes_workspace(
    tmp_path: Path,
) -> None:
    service, projects, repositories = _service(tmp_path)
    project = await _seed_project(projects)

    with pytest.raises(SourceImportError):
        await service.import_repository(
            project_id=project.id,
            source_type=RepositorySourceType.GIT,
            source_ref="https://example.com/org/repo.git",
            display_name="repo",
            source=_FailingSource(),
        )

    [repository] = repositories._repositories.values()  # noqa: SLF001
    assert repository.status == RepositoryStatus.FAILED
    assert repository.error_message == "simulated clone failure"
    assert not Path(repository.workspace_path).exists()
