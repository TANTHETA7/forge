"""Ports the parsing workflow depends on, each implemented by infrastructure and
injected into `application/parsing/service.py`.

Purpose:       Let the application layer discover files, select a parser, and
                persist results without importing tree-sitter, filesystem walking,
                or SQLAlchemy directly — the same "application depends on
                abstractions, infrastructure implements them" rule Phase 2 already
                established for repository import (see
                domain/repository/ports.py).
Responsibility: Interfaces only — no implementation.
Depends on:    domain/parsing/entities.py.
Depended on by: application/parsing/service.py; implemented by
                infrastructure/parsing/*.py, infrastructure/persistence/
                parsed_file_repository_impl.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from forge.domain.parsing.entities import (
    DiscoveredFile,
    Language,
    ParsedFile,
    ParseError,
    ParseResult,
    SkippedFile,
    Symbol,
    SymbolKind,
)


class LanguageParser(Protocol):
    """Parses one file's source into Forge's normalized model. Implemented once
    per language in infrastructure/parsing/*.py — no tree-sitter (or any other
    parser-library) type is visible past this boundary.
    """

    language: Language
    """Which `Language` this parser handles — what `ParserRegistry` matches on."""

    def parse(self, *, repository_id: UUID, file_path: str, source: bytes) -> ParsedFile:
        """Parse `source` (the raw bytes of `file_path`) into a `ParsedFile`.

        Must not raise for merely-malformed-but-recoverable source — tree-sitter's
        error recovery means a syntax error rarely prevents extracting *some*
        structure; implementations should extract what they can and let the
        caller's error status reflect what was lost, not abort outright. Raises
        `domain/errors.py::ParseFailure` only when nothing usable can be produced
        at all (e.g. the language's grammar can't parse this content as this
        language in any recognizable way).
        """
        ...


class FileDiscovery(Protocol):
    """Walks a repository workspace, yielding candidate file content (or why a
    file was excluded). See infrastructure/parsing/file_discovery.py for the
    concrete implementation and the security note on why `workspace` must always
    originate from `Repository.workspace_path`, never client input.
    """

    def discover(self, workspace: Path) -> Iterator[DiscoveredFile | SkippedFile]: ...


class ParserRegistry(Protocol):
    """Selects the `LanguageParser` for a given file, by path."""

    def parser_for(self, file_path: str) -> LanguageParser | None:
        """Return the parser for `file_path`'s detected language, or `None` if the
        file's language isn't supported. `None` is not an error — the caller
        records it as a skipped file (see infrastructure/parsing/file_discovery.py),
        never as a `ParseError`.
        """
        ...


class ParsedFileRepository(Protocol):
    """Persistence port for a repository's parse results."""

    async def save_parse_result(self, result: ParseResult) -> None:
        """Replace any existing parsed data for `result.repository_id` with
        `result`, atomically. Re-parsing a repository is idempotent — there is no
        Phase 3 requirement for incremental/partial persistence."""
        ...

    async def get_files(self, repository_id: UUID) -> list[ParsedFile]:
        """Every parsed file for `repository_id`, most-recently-parsed first is
        not guaranteed — callers needing an order should sort by `path`."""
        ...

    async def get_symbols(
        self,
        repository_id: UUID,
        *,
        kind: SymbolKind | None = None,
        file_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Symbol]:
        """Symbols for `repository_id`, optionally filtered by `kind` and/or
        `file_id`, paginated by `limit`/`offset`."""
        ...

    async def get_symbol(self, symbol_id: UUID) -> Symbol | None:
        """A single symbol by id, or `None` if it doesn't exist."""
        ...

    async def get_errors(self, repository_id: UUID) -> list[ParseError]:
        """Every recorded parse failure for `repository_id`'s most recent parse
        run."""
        ...

    async def get_last_parsed_at(self, repository_id: UUID) -> datetime | None:
        """When `repository_id` was most recently parsed, or `None` if it has
        never been parsed. Added in Phase 6 (docs/architecture/
        06-code-intelligence.md, "Graph freshness") — exposes the
        already-stored `parsed_files.parsed_at` column (present since Phase
        3) through the domain port for the first time; no schema change."""
        ...
