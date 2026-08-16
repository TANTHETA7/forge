"""SQLAlchemy implementation of `domain/parsing/ports.py::ParsedFileRepository`.

Purpose:       Persist and retrieve a repository's `ParseResult` in Postgres.
Responsibility: Translate between the domain entities and the ORM rows
                (persistence/models.py's Phase 3 tables) only — no parsing logic.
Depends on:    sqlalchemy, domain/parsing/entities.py, infrastructure/persistence/models.py.
Depended on by: infrastructure/persistence/dependencies.py.

Re-parsing a repository is idempotent by replacement, not merge: `save_parse_result`
deletes the repository's existing `parsed_files`/`parse_errors` rows (the former
cascades, at the database level, through `symbols` -> `parameters` and `imports` —
see models.py's Phase 3 section) and inserts the new result — there is no Phase 3
requirement for incremental/partial persistence.

`Parameter` and `ParseError` have no `id` of their own in the domain model (see
domain/parsing/entities.py — neither is independently referenced by anything, both
are always reached through their owning `Symbol`/`ParseResult`); their ORM rows
still need a primary key, minted here at insert time with `uuid4()`, never
round-tripped back into the domain entities on read.

Persistence performance (a real, measured constraint — not speculative): a large
real-world repository can produce hundreds of thousands of `symbols`/`parameters`/
`call_sites`/`imports` rows (Django's own checkout: ~2,928 files, ~43,625 symbols,
~172,062 call sites, ~48,705 parameters, ~12,052 imports — ~279,372 rows total for
one `save_parse_result` call). Building that many individual ORM instances and
handing them to `Session.add()` one at a time relies on SQLAlchemy's unit-of-work
to batch them back into efficient multi-row `INSERT`s at flush time — and it does
not reliably do so here (confirmed empirically against a real Postgres instance:
the resulting flush executed genuine single-row `INSERT`s, one full network round
trip per row, which never completed in a practical time at Django's scale). Every
insert below therefore goes through `Session.execute(insert(Model), rows)` — SQLAlchemy's
documented Core-style ORM bulk-insert form — in bounded chunks of `_INSERT_BATCH_SIZE`
rows, which reliably engages the dialect's `insertmanyvalues` batching (one
multi-row `INSERT ... VALUES (...), (...), ...` per chunk) regardless of the unit-of-work's
per-object bookkeeping. This is an implementation/performance change only — every
row's own column values, deterministic id, and foreign key are computed exactly as
before; nothing about *what* gets persisted or *how it can be read back* changes.

Stage ordering is preserved deliberately, and is what keeps foreign keys valid
without any explicit flush between stages (a bulk `execute()` sends its `INSERT`
immediately — unlike `Session.add()`, it is never deferred to a later flush, so no
`await session.flush()` call is needed between stages):
1. `parsed_files` — no dependency.
2. `symbols` — depends on `parsed_files.id` (`file_id`) and, self-referentially,
   on an already-inserted parent's `id` (`parent_symbol_id`). List order is
   preserved (never reordered) when building the flat per-repository row list —
   `ParsedFile.symbols` is already parent-before-child in source order (the
   tree-sitter walk in infrastructure/parsing/treesitter_support.py appends a
   symbol before recursing into its children), and PostgreSQL evaluates a
   multi-row `INSERT ... VALUES (...), (...)` sequentially, so a row's
   self-referential FK check sees any earlier row in the *same* statement/chunk
   as already present. Chunk boundaries never violate this: a parent split into
   an earlier chunk than its child is inserted (and thus already visible within
   this transaction) before the child's chunk runs, since chunks execute
   sequentially, awaited in order, on this same session/transaction.
3. `parameters` / `call_sites` / `imports` — each depends only on `symbols`/
   `parsed_files` rows already inserted in stage 2/1; independent of each other.
4. `parse_errors` — no dependency.

The whole call remains exactly one transaction, committed once at the end
(`await self._session.commit()`) — if any stage's insert fails, nothing commits
and the entire result is discarded, identical to the pre-existing behavior.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.parsing.entities import (
    CallReference,
    Import,
    Language,
    Parameter,
    ParsedFile,
    ParsedFileSummary,
    ParseError,
    ParseResult,
    SourceLocation,
    Symbol,
    SymbolKind,
)
from forge.infrastructure.persistence.models import (
    Base,
    CallSiteRow,
    ImportRow,
    ParameterRow,
    ParsedFileRow,
    ParseErrorRow,
    SymbolRow,
)

# Rows per bulk-insert statement for every table in this module. Bounds two
# things at once: in-memory batch size (a large repository's full row set is
# never materialized as one Python list handed to the driver at once beyond
# this size) and each statement's bound-parameter count (the widest table,
# SymbolRow, has 12 columns — 500 rows is at most 6,000 parameters,
# comfortably under PostgreSQL/asyncpg's ~32,767-parameter ceiling per
# statement) — while still cutting network round trips by ~500x versus one
# INSERT per row. See this module's own docstring, "Persistence performance",
# for the Django-scale measurement that motivated batching at all.
_INSERT_BATCH_SIZE = 500


def _chunked[T](items: list[T], size: int) -> Iterator[list[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class SqlAlchemyParsedFileRepository:
    """A `ParsedFileRepository` backed by Postgres via SQLAlchemy's async engine."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_parse_result(self, result: ParseResult) -> None:
        await self._session.execute(
            delete(ParseErrorRow).where(ParseErrorRow.repository_id == result.repository_id)
        )
        # Cascades (ON DELETE CASCADE, see models.py) to symbols, parameters, and
        # imports for every file being replaced.
        await self._session.execute(
            delete(ParsedFileRow).where(ParsedFileRow.repository_id == result.repository_id)
        )

        await self._bulk_insert(
            ParsedFileRow,
            [_file_to_params(f, parsed_at=result.parsed_at) for f in result.files],
        )

        # Parent-before-child order preserved — see module docstring, stage 2.
        await self._bulk_insert(
            SymbolRow,
            [
                _symbol_to_params(
                    symbol, file_id=parsed_file.id, repository_id=result.repository_id
                )
                for parsed_file in result.files
                for symbol in parsed_file.symbols
            ],
        )

        await self._bulk_insert(
            ParameterRow,
            [
                _parameter_to_params(parameter, symbol_id=symbol.id)
                for parsed_file in result.files
                for symbol in parsed_file.symbols
                for parameter in symbol.parameters
            ],
        )
        await self._bulk_insert(
            CallSiteRow,
            [
                _call_to_params(call, symbol_id=symbol.id)
                for parsed_file in result.files
                for symbol in parsed_file.symbols
                for call in symbol.calls
            ],
        )
        await self._bulk_insert(
            ImportRow,
            [
                _import_to_params(
                    import_, file_id=parsed_file.id, repository_id=result.repository_id
                )
                for parsed_file in result.files
                for import_ in parsed_file.imports
            ],
        )

        await self._bulk_insert(
            ParseErrorRow,
            [
                _error_to_params(error, repository_id=result.repository_id)
                for error in result.errors
            ],
        )

        await self._session.commit()

    async def _bulk_insert(self, model: type[Base], rows: list[dict[str, Any]]) -> None:
        """Insert `rows` in `_INSERT_BATCH_SIZE`-sized chunks via a Core-style
        `Session.execute(insert(model), chunk)` call per chunk — see this
        module's own docstring, "Persistence performance", for why this
        replaces per-row `Session.add()`. A no-op for an empty `rows` (an
        empty parameter list is rejected by the driver, and there is nothing
        to insert for a file/symbol with no parameters, calls, imports, etc.)."""
        if not rows:
            return
        for chunk in _chunked(rows, _INSERT_BATCH_SIZE):
            await self._session.execute(insert(model), chunk)

    async def get_files(self, repository_id: UUID) -> list[ParsedFile]:
        # Batched, not per-file `_assemble_file` calls — a real bug found
        # validating Forge against matplotlib/matplotlib (914 files, 12,256
        # symbols): fetching each file's symbols, then each *symbol's*
        # parameters and calls, one query at a time, is 1 (files) + 914
        # (symbols per file) + 2×12,256 (parameters/calls per symbol) + 914
        # (imports per file) ≈ 26,340 sequential round trips for one
        # `get_files` call — and `GraphService.project_repository` (application/
        # graph/service.py) calls exactly this method first, so *every* graph
        # projection paid this cost too. Four queries — files, all of the
        # repository's symbols, all of their parameters+calls (via
        # `_parameters_for_many`/`_calls_for_many`), all of the repository's
        # imports — replace it, grouped back into each `ParsedFile` in Python.
        file_rows = (
            (
                await self._session.execute(
                    select(ParsedFileRow).where(ParsedFileRow.repository_id == repository_id)
                )
            )
            .scalars()
            .all()
        )
        if not file_rows:
            return []

        symbol_rows = (
            (
                await self._session.execute(
                    select(SymbolRow)
                    .where(SymbolRow.repository_id == repository_id)
                    .order_by(SymbolRow.start_line, SymbolRow.id)
                )
            )
            .scalars()
            .all()
        )
        parameters_by_symbol = await self._parameters_for_many([row.id for row in symbol_rows])
        calls_by_symbol = await self._calls_for_many([row.id for row in symbol_rows])
        symbols_by_file: dict[UUID, list[Symbol]] = defaultdict(list)
        for symbol_row in symbol_rows:
            symbols_by_file[symbol_row.file_id].append(
                _row_to_symbol(
                    symbol_row,
                    parameters_by_symbol.get(symbol_row.id, []),
                    calls_by_symbol.get(symbol_row.id, []),
                )
            )

        import_rows = (
            (
                await self._session.execute(
                    select(ImportRow)
                    .where(ImportRow.repository_id == repository_id)
                    .order_by(ImportRow.id)
                )
            )
            .scalars()
            .all()
        )
        imports_by_file: dict[UUID, list[Import]] = defaultdict(list)
        for import_row in import_rows:
            imports_by_file[import_row.file_id].append(_row_to_import(import_row))

        return [
            ParsedFile(
                id=row.id,
                repository_id=row.repository_id,
                path=row.path,
                language=Language(row.language),
                symbols=tuple(symbols_by_file.get(row.id, [])),
                imports=tuple(imports_by_file.get(row.id, [])),
                has_syntax_errors=row.has_syntax_errors,
            )
            for row in file_rows
        ]

    async def get_file_summaries(self, repository_id: UUID) -> list[ParsedFileSummary]:
        """Read the ``GET .../files`` projection without loading child rows.

        Aggregating symbols and imports independently prevents the cartesian
        multiplication a single multi-child join would introduce.  Parameters
        and call sites are intentionally absent: they are not part of this
        endpoint's response contract.
        """
        symbol_counts = (
            select(SymbolRow.file_id.label("file_id"), func.count(SymbolRow.id).label("count"))
            .where(SymbolRow.repository_id == repository_id)
            .group_by(SymbolRow.file_id)
            .subquery()
        )
        import_counts = (
            select(ImportRow.file_id.label("file_id"), func.count(ImportRow.id).label("count"))
            .where(ImportRow.repository_id == repository_id)
            .group_by(ImportRow.file_id)
            .subquery()
        )
        rows = await self._session.execute(
            select(
                ParsedFileRow.id,
                ParsedFileRow.repository_id,
                ParsedFileRow.path,
                ParsedFileRow.language,
                ParsedFileRow.has_syntax_errors,
                func.coalesce(symbol_counts.c.count, 0).label("symbol_count"),
                func.coalesce(import_counts.c.count, 0).label("import_count"),
            )
            .outerjoin(symbol_counts, symbol_counts.c.file_id == ParsedFileRow.id)
            .outerjoin(import_counts, import_counts.c.file_id == ParsedFileRow.id)
            .where(ParsedFileRow.repository_id == repository_id)
            .order_by(ParsedFileRow.path, ParsedFileRow.id)
        )
        return [
            ParsedFileSummary(
                id=row.id,
                repository_id=row.repository_id,
                path=row.path,
                language=Language(row.language),
                has_syntax_errors=row.has_syntax_errors,
                symbol_count=row.symbol_count,
                import_count=row.import_count,
            )
            for row in rows
        ]

    async def get_symbols(
        self,
        repository_id: UUID,
        *,
        kind: SymbolKind | None = None,
        file_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Symbol]:
        query = select(SymbolRow).where(SymbolRow.repository_id == repository_id)
        if kind is not None:
            query = query.where(SymbolRow.kind == kind.value)
        if file_id is not None:
            query = query.where(SymbolRow.file_id == file_id)
        # `.id` is a required secondary sort key, not cosmetic: `start_line` is
        # far from unique across a repository's symbols (many symbols across
        # different files start on the same line number), and PostgreSQL gives
        # no guarantee that a `LIMIT`/`OFFSET` pair sees the same tie-order
        # across two separate query executions — a real repository-scale
        # paginated drain of this endpoint can silently duplicate a symbol
        # across two pages while dropping another entirely. `.id` (the primary
        # key) is unique, making the ordering — and therefore each page's
        # boundary — fully deterministic.
        query = (
            query.order_by(SymbolRow.start_line, SymbolRow.id).limit(limit).offset(offset)
        )

        rows = (await self._session.execute(query)).scalars().all()
        # Batched, not one `_parameters_for`/`_calls_for` call per row — same
        # fix, same reason, as `get_files` above.
        symbol_ids = [row.id for row in rows]
        parameters_by_symbol = await self._parameters_for_many(symbol_ids)
        calls_by_symbol = await self._calls_for_many(symbol_ids)
        return [
            _row_to_symbol(
                row, parameters_by_symbol.get(row.id, []), calls_by_symbol.get(row.id, [])
            )
            for row in rows
        ]

    async def get_symbol(self, symbol_id: UUID) -> Symbol | None:
        row = await self._session.get(SymbolRow, symbol_id)
        if row is None:
            return None
        parameters = await self._parameters_for(symbol_id)
        calls = await self._calls_for(symbol_id)
        return _row_to_symbol(row, parameters, calls)

    async def get_errors(self, repository_id: UUID) -> list[ParseError]:
        rows = (
            (
                await self._session.execute(
                    select(ParseErrorRow).where(ParseErrorRow.repository_id == repository_id)
                )
            )
            .scalars()
            .all()
        )
        return [
            ParseError(file_path=row.file_path, stage=row.stage, message=row.message)
            for row in rows
        ]

    async def get_last_parsed_at(self, repository_id: UUID) -> datetime | None:
        result = await self._session.execute(
            select(func.max(ParsedFileRow.parsed_at)).where(
                ParsedFileRow.repository_id == repository_id
            )
        )
        return result.scalar_one_or_none()

    async def _parameters_for(self, symbol_id: UUID) -> list[Parameter]:
        rows = (
            (
                await self._session.execute(
                    select(ParameterRow)
                    .where(ParameterRow.symbol_id == symbol_id)
                    .order_by(ParameterRow.position)
                )
            )
            .scalars()
            .all()
        )
        return [
            Parameter(
                name=row.name,
                position=row.position,
                annotation=row.annotation,
                default_value=row.default_value,
            )
            for row in rows
        ]

    async def _calls_for(self, symbol_id: UUID) -> list[CallReference]:
        rows = (
            (
                await self._session.execute(
                    select(CallSiteRow)
                    .where(CallSiteRow.symbol_id == symbol_id)
                    # `.id` tiebreaker: `call_sites` has no `start_column`,
                    # so multiple calls on the same `start_line` (a real,
                    # common case) tie on `start_line` alone — deterministic
                    # (if arbitrary) ordering, not one that can vary between
                    # two reads of the same data.
                    .order_by(CallSiteRow.start_line, CallSiteRow.id)
                )
            )
            .scalars()
            .all()
        )
        return [
            CallReference(
                callee_expression=row.callee_expression,
                location=SourceLocation(
                    start_line=row.start_line,
                    end_line=row.end_line,
                    start_column=None,
                    end_column=None,
                ),
            )
            for row in rows
        ]

    async def _parameters_for_many(self, symbol_ids: list[UUID]) -> dict[UUID, list[Parameter]]:
        """`get_files`/`get_symbols`' batched counterpart to `_parameters_for`
        — one `WHERE symbol_id IN (...)` query for every symbol in the batch,
        not one query per symbol (see `get_files`' own docstring). A no-op
        for an empty `symbol_ids` (an empty `IN (...)` is rejected by the
        driver, and there is nothing to fetch for zero symbols)."""
        if not symbol_ids:
            return {}
        rows = (
            (
                await self._session.execute(
                    select(ParameterRow)
                    .where(ParameterRow.symbol_id.in_(symbol_ids))
                    .order_by(ParameterRow.symbol_id, ParameterRow.position)
                )
            )
            .scalars()
            .all()
        )
        grouped: dict[UUID, list[Parameter]] = defaultdict(list)
        for row in rows:
            grouped[row.symbol_id].append(
                Parameter(
                    name=row.name,
                    position=row.position,
                    annotation=row.annotation,
                    default_value=row.default_value,
                )
            )
        return grouped

    async def _calls_for_many(self, symbol_ids: list[UUID]) -> dict[UUID, list[CallReference]]:
        """`get_files`/`get_symbols`' batched counterpart to `_calls_for` —
        see `_parameters_for_many`'s own docstring for the full rationale."""
        if not symbol_ids:
            return {}
        rows = (
            (
                await self._session.execute(
                    select(CallSiteRow)
                    .where(CallSiteRow.symbol_id.in_(symbol_ids))
                    .order_by(CallSiteRow.symbol_id, CallSiteRow.start_line, CallSiteRow.id)
                )
            )
            .scalars()
            .all()
        )
        grouped: dict[UUID, list[CallReference]] = defaultdict(list)
        for row in rows:
            grouped[row.symbol_id].append(
                CallReference(
                    callee_expression=row.callee_expression,
                    location=SourceLocation(
                        start_line=row.start_line,
                        end_line=row.end_line,
                        start_column=None,
                        end_column=None,
                    ),
                )
            )
        return grouped


def _file_to_params(parsed_file: ParsedFile, *, parsed_at: datetime) -> dict[str, Any]:
    return {
        "id": parsed_file.id,
        "repository_id": parsed_file.repository_id,
        "path": parsed_file.path,
        "language": parsed_file.language.value,
        "has_syntax_errors": parsed_file.has_syntax_errors,
        "parsed_at": parsed_at,
    }


def _symbol_to_params(symbol: Symbol, *, file_id: UUID, repository_id: UUID) -> dict[str, Any]:
    return {
        "id": symbol.id,
        "file_id": file_id,
        "repository_id": repository_id,
        "parent_symbol_id": symbol.parent_symbol_id,
        "kind": symbol.kind.value,
        "name": symbol.name,
        "qualified_name": symbol.qualified_name,
        "start_line": symbol.location.start_line,
        "end_line": symbol.location.end_line,
        "start_column": symbol.location.start_column,
        "end_column": symbol.location.end_column,
        "base_class_names": list(symbol.base_class_names) or None,
    }


def _parameter_to_params(parameter: Parameter, *, symbol_id: UUID) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "symbol_id": symbol_id,
        "name": parameter.name,
        "position": parameter.position,
        "annotation": parameter.annotation,
        "default_value": parameter.default_value,
    }


def _call_to_params(call: CallReference, *, symbol_id: UUID) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "symbol_id": symbol_id,
        "callee_expression": call.callee_expression,
        "start_line": call.location.start_line,
        "end_line": call.location.end_line,
    }


def _import_to_params(import_: Import, *, file_id: UUID, repository_id: UUID) -> dict[str, Any]:
    return {
        "id": import_.id,
        "file_id": file_id,
        "repository_id": repository_id,
        "module": import_.module,
        "imported_names": list(import_.imported_names),
        "alias": import_.alias,
        "start_line": import_.location.start_line,
        "end_line": import_.location.end_line,
    }


def _error_to_params(error: ParseError, *, repository_id: UUID) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "repository_id": repository_id,
        "file_path": error.file_path,
        "stage": error.stage,
        "message": error.message,
        "occurred_at": datetime.now(UTC),
    }


def _row_to_symbol(
    row: SymbolRow, parameters: list[Parameter], calls: list[CallReference]
) -> Symbol:
    return Symbol(
        id=row.id,
        kind=SymbolKind(row.kind),
        name=row.name,
        qualified_name=row.qualified_name,
        location=SourceLocation(
            start_line=row.start_line,
            end_line=row.end_line,
            start_column=row.start_column,
            end_column=row.end_column,
        ),
        parameters=tuple(parameters),
        parent_symbol_id=row.parent_symbol_id,
        base_class_names=tuple(row.base_class_names or ()),
        calls=tuple(calls),
    )


def _row_to_import(row: ImportRow) -> Import:
    return Import(
        id=row.id,
        module=row.module,
        imported_names=tuple(row.imported_names),
        alias=row.alias,
        location=SourceLocation(
            start_line=row.start_line, end_line=row.end_line, start_column=None, end_column=None
        ),
    )
