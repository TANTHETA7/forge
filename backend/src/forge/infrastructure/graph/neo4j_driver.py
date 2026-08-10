"""Async Neo4j driver lifecycle, constraints, and health check.

Purpose:       One cached `AsyncDriver` per process and a one-time
                constraint-creation call — the exact Neo4j counterpart to
                `infrastructure/persistence/database.py`'s `_get_engine`/
                `ensure_schema` for Postgres. Deliberately NOT FastAPI-aware
                (no `Depends`) — that wiring lives in
                infrastructure/graph/dependencies.py, exactly mirroring the
                database.py/persistence-dependencies.py split.
Responsibility: Connection lifecycle only — no Cypher queries, no domain
                mapping. `Neo4jGraphRepository` (neo4j_graph_repository.py)
                is the only module that runs Cypher against a session opened
                from the driver this module hands out.
Depends on:    neo4j (async driver API), core/config.py.
Depended on by: infrastructure/graph/dependencies.py.

Lazy, not startup-time: `ensure_constraints()` is only ever called on first
graph-projection use (mirrors `ensure_schema()`'s own reasoning) so Phases
1-4 keep working unchanged with no Neo4j available at all — proven directly
by every existing test file continuing to pass with zero Neo4j dependency.
"""

from __future__ import annotations

from functools import lru_cache

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable, SessionExpired

from forge.core.config import Settings

_constraints_ready = False

# Idempotent by construction (`IF NOT EXISTS`) — safe to re-run every process
# start, and safe to re-run if `_constraints_ready` is ever reset (e.g. tests).
_CONSTRAINT_STATEMENTS = (
    "CREATE CONSTRAINT repository_id_unique IF NOT EXISTS "
    "FOR (r:Repository) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT file_id_unique IF NOT EXISTS FOR (f:File) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT symbol_id_unique IF NOT EXISTS FOR (s:Symbol) REQUIRE s.id IS UNIQUE",
    "CREATE INDEX file_repository_id IF NOT EXISTS FOR (f:File) ON (f.repository_id)",
    "CREATE INDEX symbol_repository_id IF NOT EXISTS FOR (s:Symbol) ON (s.repository_id)",
    "CREATE INDEX symbol_kind IF NOT EXISTS FOR (s:Symbol) ON (s.kind)",
)

# Exceptions that mean "Neo4j is unreachable/unusable right now" rather than
# "the query itself is wrong" — translated to `GraphUnavailableError` by
# neo4j_graph_repository.py, never surfaced raw past infrastructure.
UNAVAILABLE_EXCEPTIONS = (ServiceUnavailable, AuthError, SessionExpired)


@lru_cache
def _get_driver(uri: str, user: str, password: str) -> AsyncDriver:
    return AsyncGraphDatabase.driver(uri, auth=(user, password))


def get_driver(settings: Settings) -> AsyncDriver:
    """Return the process-wide cached `AsyncDriver` for `settings`'
    connection details."""
    return _get_driver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)


async def ping(driver: AsyncDriver) -> bool:
    """Whether Neo4j is currently reachable and authenticated. Never raises —
    any of `UNAVAILABLE_EXCEPTIONS` is treated as "not reachable", matching
    `tests/integration/conftest.py::_postgres_reachable`'s own posture for
    Postgres."""
    try:
        async with driver.session() as session:
            await session.run("RETURN 1")
    except UNAVAILABLE_EXCEPTIONS:
        return False
    return True


async def ensure_constraints(settings: Settings) -> None:
    """Create every uniqueness constraint/index on first use if they don't
    exist yet. A no-op after the first successful call in this process —
    exactly `infrastructure/persistence/database.py::ensure_schema`'s own
    pattern, for the same reason (Phase 1's health slice, and every Phase
    1-4 route, must keep working with no Neo4j available)."""
    global _constraints_ready
    if _constraints_ready:
        return
    driver = get_driver(settings)
    async with driver.session() as session:
        for statement in _CONSTRAINT_STATEMENTS:
            await session.run(statement)
    _constraints_ready = True
