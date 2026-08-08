"""End-to-end test against a REAL PostgreSQL instance.

Scope: unlike tests/integration/test_repository_import_api.py (which overrides
persistence with the in-memory fakes from tests/fakes.py so the API contract can be
tested without any backing service running), this file deliberately does NOT
override persistence — it exercises the real asyncpg driver through the real
SQLAlchemy models. This is the only place in the suite that can catch a
driver/schema-level defect like the naive-vs-timezone-aware datetime column bug:
the in-memory fakes never touch a DB driver, so they pass regardless of column type.

Requires `infra/docker/docker-compose.yml`'s postgres service reachable at
localhost:5432 — skipped (not failed) if it isn't, matching the "Docker not always
available" limitation already disclosed in docs/architecture/01-system-architecture.md.
Each test gets a freshly dropped-and-recreated schema so tests don't leak state into
each other or depend on run order.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from forge.core.app_factory import create_app
from forge.core.config import Settings, get_settings
from forge.infrastructure.persistence import database
from forge.infrastructure.persistence.models import Base

_DSN_ASYNCPG = "postgresql://forge:forge@localhost:5432/forge"
_DSN_SQLALCHEMY = "postgresql+asyncpg://forge:forge@localhost:5432/forge"


async def _postgres_reachable() -> bool:
    try:
        connection = await asyncpg.connect(_DSN_ASYNCPG, timeout=2)
    except (OSError, asyncpg.PostgresError):
        return False
    await connection.close()
    return True


@pytest_asyncio.fixture
async def postgres_schema() -> AsyncIterator[None]:
    if not await _postgres_reachable():
        pytest.skip(
            "Postgres not reachable at localhost:5432 — start it via "
            "`docker compose -f infra/docker/docker-compose.yml up -d postgres`"
        )

    engine = create_async_engine(_DSN_SQLALCHEMY)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()

    # database.ensure_schema() caches "already ready" per process; a stale True from
    # an earlier test would make it skip creating the schema we just dropped.
    database._schema_ready = False

    # database._get_engine() is process-wide `@lru_cache`d — correct for the real
    # server (one process, one event loop, for its whole lifetime) but wrong across
    # tests: pytest-asyncio gives each test function its own event loop, and an
    # asyncpg connection pool opened under a previous test's (now-closed) loop
    # raises `RuntimeError: Event loop is closed` the moment a later test reuses it.
    # Clearing the cache here forces a fresh engine, bound to *this* test's loop,
    # without changing anything about how the real app caches its engine.
    database._get_engine.cache_clear()

    yield

    engine = create_async_engine(_DSN_SQLALCHEMY)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    database._schema_ready = False
    database._get_engine.cache_clear()


@pytest.fixture
def client(postgres_schema: None, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        postgres_dsn=_DSN_SQLALCHEMY,
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
