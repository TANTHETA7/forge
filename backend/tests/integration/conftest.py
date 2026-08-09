"""Shared fixtures for tests that run against a REAL PostgreSQL instance.

Extracted from `test_postgres_persistence.py` (Phase 2) so `test_postgres_
parsing_persistence.py` and `test_real_repository_parsing.py` (Phase 3) don't each
carry their own copy. Requires `infra/docker/docker-compose.yml`'s postgres
service reachable at localhost:5432 — skipped (not failed) if it isn't, matching
the "Docker not always available" limitation already disclosed in
docs/architecture/01-system-architecture.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from forge.infrastructure.persistence import database
from forge.infrastructure.persistence.models import Base

DSN_ASYNCPG = "postgresql://forge:forge@localhost:5432/forge"
DSN_SQLALCHEMY = "postgresql+asyncpg://forge:forge@localhost:5432/forge"


async def _postgres_reachable() -> bool:
    try:
        connection = await asyncpg.connect(DSN_ASYNCPG, timeout=2)
    except (OSError, asyncpg.PostgresError):
        return False
    await connection.close()
    return True


@pytest_asyncio.fixture
async def postgres_schema() -> AsyncIterator[None]:
    """Skip if Postgres isn't reachable; otherwise drop-and-recreate every table
    before the test and drop them again after, so tests don't leak state into
    each other or depend on run order."""
    if not await _postgres_reachable():
        pytest.skip(
            "Postgres not reachable at localhost:5432 — start it via "
            "`docker compose -f infra/docker/docker-compose.yml up -d postgres`"
        )

    engine = create_async_engine(DSN_SQLALCHEMY)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()

    # database.ensure_schema() caches "already ready" per process; a stale True
    # from an earlier test would make it skip creating the schema we just
    # dropped.
    database._schema_ready = False

    # database._get_engine() is process-wide `@lru_cache`d — correct for the real
    # server (one process, one event loop, for its whole lifetime) but wrong
    # across tests: pytest-asyncio gives each test function its own event loop,
    # and an asyncpg connection pool opened under a previous test's (now-closed)
    # loop raises `RuntimeError: Event loop is closed` the moment a later test
    # reuses it. Clearing the cache here forces a fresh engine, bound to *this*
    # test's loop, without changing anything about how the real app caches its
    # engine.
    database._get_engine.cache_clear()

    yield

    engine = create_async_engine(DSN_SQLALCHEMY)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    database._schema_ready = False
    database._get_engine.cache_clear()
