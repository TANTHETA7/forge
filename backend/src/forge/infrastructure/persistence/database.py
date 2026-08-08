"""Async SQLAlchemy engine/session wiring.

Purpose:       One cached engine per process, one session per request, and a
                one-time schema-creation call for this phase's `create_all`-based
                setup (see models.py for why this isn't Alembic yet).
Responsibility: Connection lifecycle only — no queries, no models.
Depends on:    sqlalchemy[asyncio], core/config.py, infrastructure/persistence/models.py.
Depended on by: infrastructure/persistence/dependencies.py.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from forge.core.config import Settings
from forge.infrastructure.persistence.models import Base

_schema_ready = False


@lru_cache
def _get_engine(dsn: str) -> AsyncEngine:
    return create_async_engine(dsn, pool_pre_ping=True)


async def ensure_schema(settings: Settings) -> None:
    """Create tables on first use if they don't exist yet. A no-op after the first
    successful call in this process. Deliberately not run at application startup
    (see `core/app_factory.py`) so the Phase 1 health slice keeps working with no
    Postgres available, unchanged."""
    global _schema_ready
    if _schema_ready:
        return
    engine = _get_engine(settings.postgres_dsn)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    _schema_ready = True


def get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    engine = _get_engine(settings.postgres_dsn)
    return async_sessionmaker(engine, expire_on_commit=False)
