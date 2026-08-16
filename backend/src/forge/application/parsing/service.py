"""Parsing application service.

Purpose:       Orchestrate the Phase 3 workflow — discover files in an already-
                imported repository's workspace, detect each file's language,
                parse it, and persist the normalized result.
Responsibility: Sequencing only. It never touches the filesystem or a tree-sitter
                parser directly — those are reached exclusively through the ports
                this class is constructed with (domain/parsing/ports.py), the
                same rule Phase 2's RepositoryImportService already follows for
                its own ports.

                A single file's failure (unreadable, or the language parser
                raising `ParseFailure` or anything else) is caught, recorded as a
                `ParseError`, and the loop continues — parsing the rest of the
                repository never stops because one file is broken. Only failing
                to load the `Repository` itself, or it not being `READY`, aborts
                the whole run (nothing to parse without a materialized workspace).

                Blocking I/O (the filesystem walk, each parse call) runs on a
                worker thread via `anyio.to_thread.run_sync`, mirroring
                application/repository_import/service.py's established pattern.
Depends on:    domain/parsing/ports.py, domain/repository/ports.py,
                domain/errors.py, anyio.
Depended on by: api/parsing.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import anyio.to_thread

from forge.domain.errors import NotFoundError, ParseFailure, UnsupportedRepositoryStateError
from forge.domain.parsing.entities import (
    DiscoveredFile,
    ParsedFile,
    ParsedFileSummary,
    ParseError,
    ParseResult,
    SkippedFile,
    Symbol,
    SymbolKind,
)
from forge.domain.parsing.ports import (
    FileDiscovery,
    LanguageParser,
    ParsedFileRepository,
    ParserRegistry,
)
from forge.domain.repository.entities import RepositoryStatus
from forge.domain.repository.ports import RepositoryRepository


class ParsingService:
    def __init__(
        self,
        repositories: RepositoryRepository,
        parsed_files: ParsedFileRepository,
        discovery: FileDiscovery,
        registry: ParserRegistry,
    ) -> None:
        self._repositories = repositories
        self._parsed_files = parsed_files
        self._discovery = discovery
        self._registry = registry

    async def parse_repository(self, repository_id: UUID) -> ParseResult:
        """Run the full parse workflow and return (and persist) the result.

        Raises:
            NotFoundError: `repository_id` doesn't exist.
            UnsupportedRepositoryStateError: the repository exists but isn't
                `READY` yet (still importing, or the import failed) — there is no
                materialized workspace to parse.
        """
        repository = await self._repositories.get_by_id(repository_id)
        if repository is None:
            raise NotFoundError(f"Repository {repository_id} not found")
        if repository.status is not RepositoryStatus.READY:
            raise UnsupportedRepositoryStateError(
                f"Repository {repository_id} is {repository.status.value!r}, "
                "not ready to parse — it must be READY"
            )

        workspace = Path(repository.workspace_path)
        entries = await anyio.to_thread.run_sync(lambda: list(self._discovery.discover(workspace)))

        files: list[ParsedFile] = []
        errors: list[ParseError] = []

        for entry in entries:
            if isinstance(entry, SkippedFile):
                if entry.stage is not None:
                    errors.append(
                        ParseError(
                            file_path=entry.relative_path, stage=entry.stage, message=entry.reason
                        )
                    )
                # stage=None is a deliberate policy skip (binary, oversized) —
                # not an error, nothing recorded.
                continue

            parser = self._registry.parser_for(entry.relative_path)
            if parser is None:
                # Unsupported language — a normal, expected outcome, not a
                # failure (domain/parsing/ports.py::ParserRegistry.parser_for).
                continue

            parsed = await self._parse_one(repository_id, entry, parser, errors)
            if parsed is not None:
                files.append(parsed)

        result = ParseResult(
            repository_id=repository_id,
            files=tuple(files),
            errors=tuple(errors),
            parsed_at=datetime.now(UTC),
        )
        await self._parsed_files.save_parse_result(result)
        return result

    async def _parse_one(
        self,
        repository_id: UUID,
        entry: DiscoveredFile,
        parser: LanguageParser,
        errors: list[ParseError],
    ) -> ParsedFile | None:
        try:
            return await anyio.to_thread.run_sync(
                lambda: parser.parse(
                    repository_id=repository_id,
                    file_path=entry.relative_path,
                    source=entry.content,
                )
            )
        except ParseFailure as exc:
            errors.append(
                ParseError(file_path=entry.relative_path, stage="parse", message=str(exc))
            )
        except Exception as exc:  # a bug in one file's extraction must not abort
            # the rest of the repository — see this module's own docstring.
            errors.append(
                ParseError(
                    file_path=entry.relative_path,
                    stage="parse",
                    message=f"unexpected failure: {exc}",
                )
            )
        return None

    async def get_files(self, repository_id: UUID) -> list[ParsedFile]:
        await self._require_repository(repository_id)
        return await self._parsed_files.get_files(repository_id)

    async def get_file_summaries(self, repository_id: UUID) -> list[ParsedFileSummary]:
        await self._require_repository(repository_id)
        return await self._parsed_files.get_file_summaries(repository_id)

    async def get_symbols(
        self,
        repository_id: UUID,
        *,
        kind: SymbolKind | None = None,
        file_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Symbol]:
        await self._require_repository(repository_id)
        return await self._parsed_files.get_symbols(
            repository_id, kind=kind, file_id=file_id, limit=limit, offset=offset
        )

    async def get_symbol(self, symbol_id: UUID) -> Symbol:
        symbol = await self._parsed_files.get_symbol(symbol_id)
        if symbol is None:
            raise NotFoundError(f"Symbol {symbol_id} not found")
        return symbol

    async def get_errors(self, repository_id: UUID) -> list[ParseError]:
        await self._require_repository(repository_id)
        return await self._parsed_files.get_errors(repository_id)

    async def _require_repository(self, repository_id: UUID) -> None:
        if await self._repositories.get_by_id(repository_id) is None:
            raise NotFoundError(f"Repository {repository_id} not found")
