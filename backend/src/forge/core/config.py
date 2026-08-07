"""Application configuration.

Single source of truth for runtime settings. Every module that needs configuration
receives a ``Settings`` instance via dependency injection (see :func:`get_settings`)
rather than reading environment variables directly — this keeps every consumer
trivially testable with literal values.

Purpose:       Centralize environment-derived configuration.
Depends on:    pydantic-settings only.
Depended on by: core/app_factory.py, and (from Phase 2 onward) any
                application/infrastructure module needing a connection string,
                secret, or feature flag.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment variables or a `.env` file.

    Fields are grouped by the subsystem that owns them. Fields for services not yet
    wired into the application (Postgres, Neo4j) are declared now because
    `infra/docker/docker-compose.yml` already provisions those services and later
    phases will consume these values immediately — declaring them here keeps
    Phase 1's "Dependency Management" deliverable honest without adding any logic
    that uses them yet.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # -- Application --
    app_name: str = "Forge"
    environment: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    cors_allow_origins: list[str] = ["http://localhost:5173"]

    # -- PostgreSQL (consumed starting Phase 2: Repository Import) --
    postgres_dsn: str = "postgresql+asyncpg://forge:forge@localhost:5432/forge"

    # -- Neo4j (consumed starting Phase 5: Knowledge Graph) --
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "forge-dev-password"

    # -- JWT auth (consumed once the auth module lands) --
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    Cached with ``lru_cache`` so environment parsing happens once per process;
    FastAPI route handlers depend on this via ``Depends(get_settings)``.
    """
    return Settings()
