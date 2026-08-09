"""End-to-end test against a REAL PostgreSQL instance.

Scope: unlike tests/integration/test_repository_import_api.py (which overrides
persistence with the in-memory fakes from tests/fakes.py so the API contract can be
tested without any backing service running), this file deliberately does NOT
override persistence — it exercises the real asyncpg driver through the real
SQLAlchemy models. This is the only place in the suite that can catch a
driver/schema-level defect like the naive-vs-timezone-aware datetime column bug:
the in-memory fakes never touch a DB driver, so they pass regardless of column type.

The `postgres_schema` fixture (skip-if-unreachable, drop-and-recreate per test) is
shared via tests/integration/conftest.py — test_postgres_parsing_persistence.py and
test_real_repository_parsing.py (Phase 3) use the same one.
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
from tests.integration.conftest import DSN_SQLALCHEMY


@pytest.fixture
def client(postgres_schema: None, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        postgres_dsn=DSN_SQLALCHEMY,
        workspace_root_dir=str(tmp_path / "workspaces"),
    )
    with TestClient(app) as test_client:
        yield test_client


def _make_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("README.md", "hello forge")
        zf.writestr("src/main.py", "print('hi')\n")
    return buffer.getvalue()


def test_create_project_persists_to_real_postgres(client: TestClient) -> None:
    """Reproduces the reported bug verbatim: POST /api/v1/projects against real
    Postgres used to return 500 (asyncpg.exceptions.DataError: can't subtract
    offset-naive and offset-aware datetimes) because created_at/updated_at were
    TIMESTAMP WITHOUT TIME ZONE columns receiving the domain layer's
    timezone-aware UTC values."""
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "Forge Phase 2 Test",
            "description": (
                "End-to-end validation of repository import, workspace creation, "
                "metadata scanning, and PostgreSQL persistence."
            ),
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Forge Phase 2 Test"
    assert body["status"] == "created"

    # Round-trip through a second, independent request — proves the row was
    # actually committed and read back from Postgres, not just that the insert
    # didn't raise.
    read_back = client.get(f"/api/v1/projects/{body['id']}")
    assert read_back.status_code == 200
    assert read_back.json()["created_at"] == body["created_at"]


def test_repository_import_persists_to_real_postgres(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Banking System"}).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("upload.zip", _make_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["metadata"]["file_count"] == 2
    assert body["metadata"]["has_readme"] is True

    read_back = client.get(f"/api/v1/projects/{project['id']}/repositories/{body['id']}")
    assert read_back.status_code == 200
    assert read_back.json()["status"] == "ready"
    assert read_back.json()["metadata"]["scanned_at"] == body["metadata"]["scanned_at"]
