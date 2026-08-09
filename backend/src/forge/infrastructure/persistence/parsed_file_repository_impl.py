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
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.parsing.entities import (
    Import,
    Language,
    Parameter,
    ParsedFile,
    ParseError,
    ParseResult,
    SourceLocation,
    Symbol,
    SymbolKind,
)
from forge.infrastructure.persistence.models import (
    ImportRow,
    ParameterRow,
    ParsedFileRow,
    ParseErrorRow,
    SymbolRow,
)


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

        # Inserted in explicit stages, each flushed before the next: SQLAlchemy's
        # automatic per-flush dependency sort is for objects reached via a
        # `relationship()` — these rows are plain FK columns with no
        # `relationship()` declared (see models.py), so nothing here guarantees
        # `parsed_files` rows exist before `symbols`/`imports` reference them
        # unless each stage is flushed first.
        for parsed_file in result.files:
            self._session.add(_file_to_row(parsed_file, parsed_at=result.parsed_at))
        await self._session.flush()

        for parsed_file in result.files:
            for symbol in parsed_file.symbols:
                self._session.add(
                    _symbol_to_row(
                        symbol, file_id=parsed_file.id, repository_id=result.repository_id
                    )
                )
        await self._session.flush()

        for parsed_file in result.files:
            for symbol in parsed_file.symbols:
                for parameter in symbol.parameters:
                    self._session.add(_parameter_to_row(parameter, symbol_id=symbol.id))
            for import_ in parsed_file.imports:
                self._session.add(
                    _import_to_row(
                        import_, file_id=parsed_file.id, repository_id=result.repository_id
                    )
                )

        for error in result.errors:
            self._session.add(_error_to_row(error, repository_id=result.repository_id))

        await self._session.commit()

    async def get_files(self, repository_id: UUID) -> list[ParsedFile]:
        file_rows = (
            (
                await self._session.execute(
                    select(ParsedFileRow).where(ParsedFileRow.repository_id == repository_id)
                )
            )
            .scalars()
            .all()
        )
        return [await self._assemble_file(row) for row in file_rows]

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
        query = query.order_by(SymbolRow.start_line).limit(limit).offset(offset)

        rows = (await self._session.execute(query)).scalars().all()
        symbols = []
        for row in rows:
            parameters = await self._parameters_for(row.id)
            symbols.append(_row_to_symbol(row, parameters))
        return symbols

    async def get_symbol(self, symbol_id: UUID) -> Symbol | None:
        row = await self._session.get(SymbolRow, symbol_id)
        if row is None:
            return None
        parameters = await self._parameters_for(symbol_id)
        return _row_to_symbol(row, parameters)

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

    async def _assemble_file(self, row: ParsedFileRow) -> ParsedFile:
        symbol_rows = (
            (await self._session.execute(select(SymbolRow).where(SymbolRow.file_id == row.id)))
            .scalars()
            .all()
        )
        symbols = []
        for symbol_row in symbol_rows:
            parameters = await self._parameters_for(symbol_row.id)
            symbols.append(_row_to_symbol(symbol_row, parameters))

        import_rows = (
            (await self._session.execute(select(ImportRow).where(ImportRow.file_id == row.id)))
            .scalars()
            .all()
        )
        imports = [_row_to_import(import_row) for import_row in import_rows]

        return ParsedFile(
            id=row.id,
            repository_id=row.repository_id,
            path=row.path,
            language=Language(row.language),
            symbols=tuple(symbols),
            imports=tuple(imports),
            has_syntax_errors=row.has_syntax_errors,
        )

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


def _file_to_row(parsed_file: ParsedFile, *, parsed_at: datetime) -> ParsedFileRow:
    return ParsedFileRow(
        id=parsed_file.id,
        repository_id=parsed_file.repository_id,
        path=parsed_file.path,
        language=parsed_file.language.value,
        has_syntax_errors=parsed_file.has_syntax_errors,
        parsed_at=parsed_at,
    )


def _symbol_to_row(symbol: Symbol, *, file_id: UUID, repository_id: UUID) -> SymbolRow:
    return SymbolRow(
        id=symbol.id,
        file_id=file_id,
        repository_id=repository_id,
        parent_symbol_id=symbol.parent_symbol_id,
        kind=symbol.kind.value,
        name=symbol.name,
        qualified_name=symbol.qualified_name,
        start_line=symbol.location.start_line,
        end_line=symbol.location.end_line,
        start_column=symbol.location.start_column,
        end_column=symbol.location.end_column,
    )


def _parameter_to_row(parameter: Parameter, *, symbol_id: UUID) -> ParameterRow:
    return ParameterRow(
        id=uuid4(),
        symbol_id=symbol_id,
        name=parameter.name,
        position=parameter.position,
        annotation=parameter.annotation,
        default_value=parameter.default_value,
    )


def _import_to_row(import_: Import, *, file_id: UUID, repository_id: UUID) -> ImportRow:
    return ImportRow(
        id=import_.id,
        file_id=file_id,
        repository_id=repository_id,
        module=import_.module,
        imported_names=list(import_.imported_names),
        alias=import_.alias,
        start_line=import_.location.start_line,
        end_line=import_.location.end_line,
    )


def _error_to_row(error: ParseError, *, repository_id: UUID) -> ParseErrorRow:
    return ParseErrorRow(
        id=uuid4(),
        repository_id=repository_id,
        file_path=error.file_path,
        stage=error.stage,
        message=error.message,
        occurred_at=datetime.now(UTC),
    )


def _row_to_symbol(row: SymbolRow, parameters: list[Parameter]) -> Symbol:
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
