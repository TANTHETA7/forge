"""Shared fixtures for tests that run against REAL PostgreSQL/Neo4j instances.

Extracted from `test_postgres_persistence.py` (Phase 2) so `test_postgres_
parsing_persistence.py` and `test_real_repository_parsing.py` (Phase 3) don't each
carry their own copy. Requires `infra/docker/docker-compose.yml`'s postgres/neo4j
services reachable at localhost:5432/localhost:7687 — skipped (not failed) if
either isn't, matching the "Docker not always available" limitation already
disclosed in docs/architecture/01-system-architecture.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from neo4j import AsyncGraphDatabase
from sqlalchemy.ext.asyncio import create_async_engine

from forge.infrastructure.graph import neo4j_driver
from forge.infrastructure.persistence import database
from forge.infrastructure.persistence.models import Base

DSN_ASYNCPG = "postgresql://forge:forge@localhost:5432/forge"
DSN_SQLALCHEMY = "postgresql+asyncpg://forge:forge@localhost:5432/forge"

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "forge-dev-password"


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


async def _neo4j_reachable() -> bool:
    try:
        driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        async with driver.session() as session:
            await session.run("RETURN 1")
        await driver.close()
    except neo4j_driver.UNAVAILABLE_EXCEPTIONS:
        return False
    return True


@pytest_asyncio.fixture
async def neo4j_graph() -> AsyncIterator[None]:
    """Skip if Neo4j isn't reachable; otherwise wipe every node/relationship
    before the test and again after, so tests don't leak graph state into
    each other or depend on run order — the Neo4j counterpart to
    `postgres_schema` above."""
    if not await _neo4j_reachable():
        pytest.skip(
            "Neo4j not reachable at localhost:7687 — start it via "
            "`docker compose -f infra/docker/docker-compose.yml up -d neo4j`"
        )

    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    async with driver.session() as session:
        await session.run("MATCH (n) DETACH DELETE n")
    await driver.close()

    # neo4j_driver.ensure_constraints() caches "already ready" per process; a
    # stale True from an earlier test is harmless here (constraints are
    # `IF NOT EXISTS`, and wiping nodes above doesn't drop them) but the
    # driver cache below has the same cross-event-loop problem
    # `postgres_schema` documents for `database._get_engine` — pytest-asyncio
    # gives each test its own event loop, and a cached `AsyncDriver` opened
    # under a previous (now-closed) loop breaks the moment a later test
    # reuses it.
    neo4j_driver._get_driver.cache_clear()

    yield

    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    async with driver.session() as session:
        await session.run("MATCH (n) DETACH DELETE n")
    await driver.close()
    neo4j_driver._get_driver.cache_clear()
