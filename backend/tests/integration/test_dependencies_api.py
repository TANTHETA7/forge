"""Integration test for the dependency-analysis HTTP surface.

Scope: full stack through the ASGI app — api -> application -> domain -> (real
tree-sitter parsers, real PythonModuleResolver, fake persistence) — proving the
routers, schemas, and DI wiring are correct end to end, mirroring
test_parsing_api.py's established approach.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient

from forge.core.app_factory import create_app
from forge.core.config import Settings, get_settings
from forge.domain.repository.entities import Repository, RepositorySourceType, RepositoryStatus
from forge.infrastructure.persistence.dependencies import (
    get_dependency_edge_repository,
    get_parsed_file_repository,
    get_project_repository,
    get_repository_repository,
)
from tests.fakes import (
    InMemoryDependencyEdgeRepository,
    InMemoryParsedFileRepository,
    InMemoryProjectRepository,
    InMemoryRepositoryRepository,
)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        workspace_root_dir=str(tmp_path / "workspaces")
    )

    shared_projects = InMemoryProjectRepository()
    shared_repositories = InMemoryRepositoryRepository()
    shared_parsed_files = InMemoryParsedFileRepository()
    shared_dependency_edges = InMemoryDependencyEdgeRepository()
    app.dependency_overrides[get_project_repository] = lambda: shared_projects
    app.dependency_overrides[get_repository_repository] = lambda: shared_repositories
    app.dependency_overrides[get_parsed_file_repository] = lambda: shared_parsed_files
    app.dependency_overrides[get_dependency_edge_repository] = lambda: shared_dependency_edges

    with TestClient(app) as test_client:
        yield test_client


def _make_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("pkg/__init__.py", "")
        zf.writestr("pkg/utils.py", "def helper():\n    pass\n")
        zf.writestr("pkg/main.py", "from .utils import helper\nfrom external_pkg import thing\n")
    return buffer.getvalue()


def _import_and_parse_ready_repository(client: TestClient) -> tuple[str, str]:
    project = client.post("/api/v1/projects", json={"name": "Dependency Test"}).json()
    repository = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("upload.zip", _make_zip_bytes(), "application/zip")},
    ).json()
    assert repository["status"] == "ready"
    parse_response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/parse"
    )
    assert parse_response.status_code == 201
    return project["id"], repository["id"]


def test_analyze_returns_201_with_summary(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/analyze-dependencies"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["repository_id"] == repository_id
    assert body["edge_count"] == 2  # pkg/main.py's two imports
    assert body["resolved_count"] == 1  # .utils resolves
    assert body["unresolved_count"] == 1  # external_pkg does not


def test_analyze_unknown_repository_returns_404(client: TestClient) -> None:
    project_id, _ = _import_and_parse_ready_repository(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/repositories/"
        "00000000-0000-0000-0000-000000000000/analyze-dependencies"
    )
    assert response.status_code == 404


def test_analyze_unparsed_repository_returns_409(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Not Parsed"}).json()
    repository = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("upload.zip", _make_zip_bytes(), "application/zip")},
    ).json()
    assert repository["status"] == "ready"  # imported, but /parse was never called

    response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/analyze-dependencies"
    )
    assert response.status_code == 409


def test_analyze_non_ready_repository_returns_409(tmp_path: Path) -> None:
    # Mirrors test_parsing_api.py's equivalent test: seed a non-READY
    # repository directly into the fake, bypassing the import flow, since
    # Phase 2's synchronous import never itself returns a non-READY repository.
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        workspace_root_dir=str(tmp_path / "workspaces")
    )
    repositories = InMemoryRepositoryRepository()
    app.dependency_overrides[get_repository_repository] = lambda: repositories
    app.dependency_overrides[get_project_repository] = lambda: InMemoryProjectRepository()
    app.dependency_overrides[get_parsed_file_repository] = lambda: InMemoryParsedFileRepository()
    app.dependency_overrides[get_dependency_edge_repository] = (
        lambda: InMemoryDependencyEdgeRepository()
    )

    now = datetime.now(UTC)
    repository_id = uuid4()
    project_id = uuid4()
    importing_repository = Repository(
        id=repository_id,
        project_id=project_id,
        source_type=RepositorySourceType.ZIP,
        source_ref="upload.zip",
        display_name="upload",
        workspace_path=str(tmp_path / "workspaces" / "does-not-exist"),
        status=RepositoryStatus.IMPORTING,
        metadata=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    anyio.run(repositories.create, importing_repository)

    with TestClient(app) as test_client:
        response = test_client.post(
            f"/api/v1/projects/{project_id}/repositories/{repository_id}/analyze-dependencies"
        )

    assert response.status_code == 409


def test_list_dependencies_after_analysis(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/analyze-dependencies")

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/dependencies"
    )

    assert response.status_code == 200
    edges = response.json()
    assert len(edges) == 2
    assert {e["raw_target_expression"] for e in edges} == {".utils", "external_pkg"}


def test_list_dependencies_filters_by_resolution_status(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/analyze-dependencies")

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/dependencies",
        params={"resolution_status": "resolved"},
    )

    assert response.status_code == 200
    edges = response.json()
    assert len(edges) == 1
    assert edges[0]["raw_target_expression"] == ".utils"


def test_get_dependency_by_id(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/analyze-dependencies")
    edges = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/dependencies"
    ).json()
    dependency_id = edges[0]["id"]

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/dependencies/{dependency_id}"
    )

    assert response.status_code == 200
    assert response.json()["id"] == dependency_id


def test_get_unknown_dependency_returns_404(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/dependencies/"
        "00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


def test_reanalysis_does_not_duplicate_edges(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/analyze-dependencies")
    second = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/analyze-dependencies"
    )

    assert second.status_code == 201
    edges = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/dependencies"
    ).json()
    assert len(edges) == 2  # not duplicated
