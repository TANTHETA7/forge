"""In-memory fakes for the Phase 2/3 persistence ports.

Purpose: Let unit/integration tests exercise application services and API routes
against real port contracts (`ProjectRepository`, `RepositoryRepository`,
`ParsedFileRepository`) without a live Postgres — real-Postgres coverage for the
SQLAlchemy implementations lives in tests/integration/test_postgres_persistence.py
and test_postgres_parsing_persistence.py instead.
"""

from __future__ import annotations

from uuid import UUID

from forge.domain.parsing.entities import ParsedFile, ParseError, ParseResult, Symbol, SymbolKind
from forge.domain.project.entities import Project
from forge.domain.repository.entities import Repository


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[UUID, Project] = {}

    async def create(self, project: Project) -> None:
        self._projects[project.id] = project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return self._projects.get(project_id)

    async def update(self, project: Project) -> None:
        self._projects[project.id] = project


class InMemoryRepositoryRepository:
    def __init__(self) -> None:
        self._repositories: dict[UUID, Repository] = {}

    async def create(self, repository: Repository) -> None:
        self._repositories[repository.id] = repository

    async def get_by_id(self, repository_id: UUID) -> Repository | None:
        return self._repositories.get(repository_id)

    async def update(self, repository: Repository) -> None:
        self._repositories[repository.id] = repository


class InMemoryParsedFileRepository:
    """Mirrors `SqlAlchemyParsedFileRepository`'s replace-on-reparse semantics —
    `save_parse_result` discards any previous result for the same repository."""

    def __init__(self) -> None:
        self._results: dict[UUID, ParseResult] = {}

    async def save_parse_result(self, result: ParseResult) -> None:
        self._results[result.repository_id] = result

    async def get_files(self, repository_id: UUID) -> list[ParsedFile]:
        result = self._results.get(repository_id)
        return list(result.files) if result else []

    async def get_symbols(
        self,
        repository_id: UUID,
        *,
        kind: SymbolKind | None = None,
        file_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Symbol]:
        result = self._results.get(repository_id)
        if result is None:
            return []
        symbols = [
            symbol
            for file in result.files
            if file_id is None or file.id == file_id
            for symbol in file.symbols
            if kind is None or symbol.kind is kind
        ]
        return symbols[offset : offset + limit]

    async def get_symbol(self, symbol_id: UUID) -> Symbol | None:
        for result in self._results.values():
            for file in result.files:
                for symbol in file.symbols:
                    if symbol.id == symbol_id:
                        return symbol
        return None

    async def get_errors(self, repository_id: UUID) -> list[ParseError]:
        result = self._results.get(repository_id)
        return list(result.errors) if result else []
