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

    # -- Repository Import (Phase 2) --
    # Root directory every imported repository's isolated workspace lives under.
    # Workspace subpaths are always server-generated UUIDs, never derived from a
    # project/repository name — see infrastructure/workspace/workspace_manager.py.
    workspace_root_dir: str = "./data/workspaces"
    # Compressed upload cap, enforced while streaming the upload to disk — the
    # first line of defense, before the archive is even opened as a ZIP.
    max_upload_bytes: int = 200 * 1024 * 1024
    # Uncompressed-size, file-count, per-file, and compression-ratio caps enforced
    # by ZipRepositorySource.validate() against the archive's central directory,
    # and independently re-enforced byte-by-byte during extraction.
    max_archive_uncompressed_bytes: int = 1024 * 1024 * 1024
    max_archive_file_count: int = 50_000
    max_archive_single_file_bytes: int = 100 * 1024 * 1024
    max_archive_compression_ratio: int = 100
    # Git clone bounds, enforced by GitRepositorySource.
    git_clone_timeout_seconds: int = 120
    max_git_repo_size_bytes: int = 1024 * 1024 * 1024

    # -- Code Parsing (Phase 3) --
    # A single file over this size is skipped (recorded as a ParseError, not
    # parsed) rather than read fully into memory — see
    # infrastructure/parsing/file_discovery.py.
    max_parse_file_bytes: int = 5 * 1024 * 1024

    # -- Code Intelligence (Phase 6) --
    # Server-enforced ceilings on graph traversal — a client's `depth`/`limit`
    # query params are checked against these inside each route handler body
    # (against this *injected* Settings object, not via FastAPI `Query(le=...)`,
    # which is evaluated once at import time and can't read a per-request
    # dependency — see api/graph_intelligence.py's `_check_depth`/`_check_limit`)
    # so a request can never ask for an unbounded traversal, regardless of what
    # it requests. Defaults match docs/architecture/06-code-intelligence.md's
    # own "Performance" section.
    graph_max_impact_depth: int = 10
    graph_max_path_depth: int = 15
    graph_max_result_limit: int = 500
    graph_default_result_limit: int = 100
    # Bounds every Neo4jGraphIntelligenceRepository query via
    # `asyncio.wait_for(...)` around the whole read, not the `neo4j` driver's
    # own per-statement `Query(timeout=...)` — that was tried first and
    # empirically found to be rejected inside a managed transaction (see
    # infrastructure/graph_intelligence/neo4j_graph_intelligence_repository.py's
    # own module docstring for the confirmed error).
    graph_query_timeout_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    Cached with ``lru_cache`` so environment parsing happens once per process;
    FastAPI route handlers depend on this via ``Depends(get_settings)``.
    """
    return Settings()
