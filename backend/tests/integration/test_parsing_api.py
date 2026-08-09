"""Integration test for the code-parsing HTTP surface.

Scope: full stack through the ASGI app — api -> application -> domain ->
(real filesystem, real tree-sitter parsers, fake persistence) — proving the
routers, schemas, and DI wiring are correct end to end. Persistence ports are
overridden with in-memory fakes (see tests/fakes.py); everything else (ZIP
import, workspace materialization, file discovery, parsing) is real, mirroring
test_repository_import_api.py's established approach.
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
    get_parsed_file_repository,
    get_project_repository,
    get_repository_repository,
)
from tests.fakes import (
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
    app.dependency_overrides[get_project_repository] = lambda: shared_projects
    app.dependency_overrides[get_repository_repository] = lambda: shared_repositories
    app.dependency_overrides[get_parsed_file_repository] = lambda: shared_parsed_files

    with TestClient(app) as test_client:
        yield test_client


def _make_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("README.md", "hello forge")  # unsupported — silently skipped
        zf.writestr("src/main.py", "class Foo:\n    def bar(self, x):\n        pass\n")
        zf.writestr("src/app.js", "function greet() {}\n")
    return buffer.getvalue()


def _import_ready_repository(client: TestClient) -> tuple[str, str]:
    project = client.post("/api/v1/projects", json={"name": "Parsing Test"}).json()
    repository = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("upload.zip", _make_zip_bytes(), "application/zip")},
    ).json()
    assert repository["status"] == "ready"
    return project["id"], repository["id"]


def test_parse_returns_201_with_summary(client: TestClient) -> None:
    project_id, repository_id = _import_ready_repository(client)

    response = client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse")

    assert response.status_code == 201
    body = response.json()
    assert body["repository_id"] == repository_id
    assert body["file_count"] == 2
    assert body["symbol_count"] == 3  # Foo, bar (main.py), greet (app.js)
    assert body["error_count"] == 0


def test_parse_unknown_repository_returns_404(client: TestClient) -> None:
    project_id, _ = _import_ready_repository(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/repositories/00000000-0000-0000-0000-000000000000/parse"
    )
    assert response.status_code == 404


def test_parse_non_ready_repository_returns_409(tmp_path: Path) -> None:
    # Phase 2's synchronous import always returns a repository already READY or
    # FAILED (never IMPORTING) — to exercise the 409 mapping at the API level
    # (not just the service-level check already covered by
    # tests/unit/test_parsing_service.py), a repository is seeded directly into
    # the fake with status=IMPORTING, bypassing the import flow entirely.
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        workspace_root_dir=str(tmp_path / "workspaces")
    )
    repositories = InMemoryRepositoryRepository()
    app.dependency_overrides[get_repository_repository] = lambda: repositories
    app.dependency_overrides[get_project_repository] = lambda: InMemoryProjectRepository()
    app.dependency_overrides[get_parsed_file_repository] = lambda: InMemoryParsedFileRepository()

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
            f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse"
        )

    assert response.status_code == 409


def test_list_files_after_parsing(client: TestClient) -> None:
    project_id, repository_id = _import_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse")

    response = client.get(f"/api/v1/projects/{project_id}/repositories/{repository_id}/files")

    assert response.status_code == 200
    files = response.json()
    assert {f["path"] for f in files} == {"src/main.py", "src/app.js"}
    assert {f["language"] for f in files} == {"python", "javascript"}


def test_list_symbols_filters_by_kind(client: TestClient) -> None:
    project_id, repository_id = _import_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse")

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/symbols",
        params={"kind": "class"},
    )

    assert response.status_code == 200
    symbols = response.json()
    assert len(symbols) == 1
    assert symbols[0]["name"] == "Foo"
    assert symbols[0]["kind"] == "class"


def test_get_symbol_by_id_includes_parameters(client: TestClient) -> None:
    project_id, repository_id = _import_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse")
    symbols = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/symbols",
        params={"kind": "method"},
    ).json()
    method_id = symbols[0]["id"]

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/symbols/{method_id}"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "bar"
    assert [p["name"] for p in body["parameters"]] == ["self", "x"]
    assert body["parent_symbol_id"] is not None


def test_get_unknown_symbol_returns_404(client: TestClient) -> None:
    project_id, repository_id = _import_ready_repository(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/symbols/"
        "00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


def test_list_parse_errors(client: TestClient) -> None:
    project_id, repository_id = _import_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse")

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse-errors"
    )

    assert response.status_code == 200
    assert response.json() == []  # nothing failed in this fixture repo


def test_reparsing_replaces_previous_results(client: TestClient) -> None:
    project_id, repository_id = _import_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse")
    second = client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse")

    assert second.status_code == 201
    files = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/files"
    ).json()
    assert len(files) == 2  # not duplicated by the second parse run
