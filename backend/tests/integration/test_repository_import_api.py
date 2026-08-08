"""Integration test for the project + repository import HTTP surface.

Scope: full stack through the ASGI app — api -> application -> domain -> (fake)
persistence — proving the routers, schemas, and DI wiring are correct end to end.
Persistence ports are overridden with in-memory fakes (see tests/fakes.py) since
this environment has no live Postgres to test against (Docker unavailable, same
disclosed limitation as Phase 1's docker-compose validation).
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forge.core.app_factory import create_app
from forge.core.config import Settings, get_settings
from forge.infrastructure.persistence.dependencies import (
    get_project_repository,
    get_repository_repository,
)
from tests.fakes import InMemoryProjectRepository, InMemoryRepositoryRepository


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        workspace_root_dir=str(tmp_path / "workspaces")
    )

    # Routes within one test must share the same fake instances (a request that
    # creates a project, then a later request that imports into it, need to see
    # the same in-memory store) — override with shared singletons, not a fresh
    # fake per call.
    shared_projects = InMemoryProjectRepository()
    shared_repositories = InMemoryRepositoryRepository()
    app.dependency_overrides[get_project_repository] = lambda: shared_projects
    app.dependency_overrides[get_repository_repository] = lambda: shared_repositories

    with TestClient(app) as test_client:
        yield test_client


def _make_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("README.md", "hello forge")
        zf.writestr("src/main.py", "print('hi')\n")
    return buffer.getvalue()


def test_create_project_returns_201(client: TestClient) -> None:
    response = client.post("/api/v1/projects", json={"name": "Banking System"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Banking System"
    assert body["status"] == "created"
    assert "id" in body


def test_get_unknown_project_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"] == "NotFoundError"


def test_zip_import_end_to_end(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Banking System"}).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("upload.zip", _make_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["source_type"] == "zip"
    assert body["metadata"]["file_count"] == 2
    assert body["metadata"]["has_readme"] is True


def test_zip_import_rejects_path_traversal_archive(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Banking System"}).json()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("../../etc/passwd", "malicious")

    response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("evil.zip", buffer.getvalue(), "application/zip")},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "UnsafeArchiveError"


def test_zip_import_into_unknown_project_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/repositories/import/zip",
        files={"file": ("upload.zip", _make_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 404


def test_git_import_rejects_non_https_url(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Banking System"}).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/git",
        json={"url": "ssh://git@github.com/org/repo.git"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "SourceValidationError"


def test_get_repository_returns_current_status(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Banking System"}).json()
    imported = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("upload.zip", _make_zip_bytes(), "application/zip")},
    ).json()

    response = client.get(f"/api/v1/projects/{project['id']}/repositories/{imported['id']}")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
