"""Ports the dependency-analysis workflow depends on, each implemented by
infrastructure and injected into `application/dependency_analysis/service.py`.

Purpose:       Let the application layer resolve imports and persist dependency
                edges without importing any language-specific resolution logic
                or SQLAlchemy directly — the same "application depends on
                abstractions, infrastructure implements them" rule Phases 2/3
                already established.
Responsibility: Interfaces only — no implementation.
Depends on:    domain/dependency_analysis/entities.py, domain/parsing/entities.py.
Depended on by: application/dependency_analysis/service.py; implemented by
                infrastructure/dependency_analysis/*.py, infrastructure/
                persistence/dependency_edge_repository_impl.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from forge.domain.dependency_analysis.entities import (
    DependencyEdge,
    DependencyKind,
    ResolutionStatus,
)
from forge.domain.parsing.entities import Import, ParsedFile


@dataclass(frozen=True, slots=True)
class ModuleResolution:
    """The outcome of resolving one `Import.module` string against a
    repository's parsed files.

    Attributes:
        status: RESOLVED, AMBIGUOUS, or UNRESOLVED.
        target_file_id: Set when `status` is RESOLVED (exactly one match) or
            AMBIGUOUS with a first/preferred candidate worth recording;
            `None` when nothing matched.
        detail: Human-readable reason — always set for AMBIGUOUS/UNRESOLVED.
    """

    status: ResolutionStatus
    target_file_id: UUID | None
    detail: str | None


class ModuleResolver(Protocol):
    """Resolves an `Import`'s module string to a file within the same
    repository. Language-specific — Python's dotted-absolute and leading-dot-
    relative import syntax resolves differently from JS/TS's relative-path-
    with-extension-trial syntax. See infrastructure/dependency_analysis/
    {python,ecmascript}_module_resolver.py.
    """

    def resolve_import(
        self, import_: Import, source_file: ParsedFile, all_files: list[ParsedFile]
    ) -> ModuleResolution:
        """Resolve `import_` (found in `source_file`) against `all_files` —
        every `ParsedFile` in the same repository. Never raises for an
        unresolvable import (a bare package import is a normal, expected
        UNRESOLVED outcome, not an error)."""
        ...


class DependencyEdgeRepository(Protocol):
    """Persistence port for a repository's dependency-analysis results."""

    async def save_analysis_result(
        self, repository_id: UUID, edges: tuple[DependencyEdge, ...]
    ) -> None:
        """Replace any existing dependency edges for `repository_id` with
        `edges`, atomically. Re-analyzing a repository is idempotent — content
        is identical across runs because edge ids are deterministic, but row
        identity is delete-and-reinsert, matching
        `ParsedFileRepository.save_parse_result`'s established pattern."""
        ...

    async def get_edges(
        self,
        repository_id: UUID,
        *,
        kind: DependencyKind | None = None,
        source_symbol_id: UUID | None = None,
        target_symbol_id: UUID | None = None,
        resolution_status: ResolutionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DependencyEdge]:
        """Dependency edges for `repository_id`, optionally filtered, paginated
        by `limit`/`offset`."""
        ...

    async def get_edge(self, dependency_id: UUID) -> DependencyEdge | None:
        """A single edge by id, or `None` if it doesn't exist."""
        ...
