"""Parsing API router.

Purpose:       Expose code parsing (trigger + read) over HTTP.
Responsibility: Translate between HTTP and application/parsing/service.py only —
                no parsing logic lives here, matching api/repositories.py's rule
                for api/repositories.py's own routers. This router is the one
                place that constructs the concrete `FileDiscovery` and
                `ParserRegistry` implementations — application code only ever
                sees the domain/parsing/ports.py interfaces.
Depends on:    application/parsing/service.py, infrastructure/parsing/*,
                api/schemas.py.
Depended on by: core/app_factory.py (registers this router).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from forge.api.schemas import (
    ParameterResponse,
    ParsedFileResponse,
    ParseErrorResponse,
    ParseSummaryResponse,
    SymbolResponse,
)
from forge.application.parsing.service import ParsingService
from forge.core.config import Settings, get_settings
from forge.domain.parsing.entities import (
    Parameter,
    ParsedFileSummary,
    ParseResult,
    Symbol,
    SymbolKind,
)
from forge.domain.parsing.ports import ParsedFileRepository
from forge.domain.repository.ports import RepositoryRepository
from forge.infrastructure.parsing.file_discovery import FilesystemFileDiscovery
from forge.infrastructure.parsing.javascript_parser import JavaScriptParser
from forge.infrastructure.parsing.python_parser import PythonParser
from forge.infrastructure.parsing.registry import DefaultParserRegistry
from forge.infrastructure.parsing.typescript_parser import TypeScriptParser
from forge.infrastructure.persistence.dependencies import (
    get_parsed_file_repository,
    get_repository_repository,
)

router = APIRouter(prefix="/projects/{project_id}/repositories/{repository_id}", tags=["parsing"])


def get_parsing_service(
    repositories: RepositoryRepository = Depends(get_repository_repository),
    parsed_files: ParsedFileRepository = Depends(get_parsed_file_repository),
    settings: Settings = Depends(get_settings),
) -> ParsingService:
    return ParsingService(
        repositories=repositories,
        parsed_files=parsed_files,
        discovery=FilesystemFileDiscovery(max_file_bytes=settings.max_parse_file_bytes),
        registry=DefaultParserRegistry(
            python=PythonParser(),
            javascript=JavaScriptParser(),
            typescript=TypeScriptParser(),
            tsx=TypeScriptParser(tsx=True),
        ),
    )


@router.post("/parse", response_model=ParseSummaryResponse, status_code=status.HTTP_201_CREATED)
async def parse_repository(
    project_id: UUID,
    repository_id: UUID,
    service: ParsingService = Depends(get_parsing_service),
) -> ParseSummaryResponse:
    """Parse a `READY` repository's workspace into Forge's normalized code model.

    404s if the repository doesn't exist; 409s if it exists but isn't `READY`
    (via api/error_handlers.py). Idempotent — re-parsing replaces any previous
    result for this repository.
    """
    result = await service.parse_repository(repository_id)
    return _to_summary(result)


@router.get("/files", response_model=list[ParsedFileResponse])
async def list_files(
    project_id: UUID,
    repository_id: UUID,
    service: ParsingService = Depends(get_parsing_service),
) -> list[ParsedFileResponse]:
    """Every parsed file for this repository, summarized (symbol/import counts,
    not the full lists — see `GET .../symbols` for those)."""
    files = await service.get_file_summaries(repository_id)
    return [_to_file_response(f) for f in files]


@router.get("/symbols", response_model=list[SymbolResponse])
async def list_symbols(
    project_id: UUID,
    repository_id: UUID,
    kind: SymbolKind | None = None,
    file_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    service: ParsingService = Depends(get_parsing_service),
) -> list[SymbolResponse]:
    """Symbols for this repository, optionally filtered by `kind`/`file_id`,
    paginated — a real repository can have thousands of symbols."""
    symbols = await service.get_symbols(
        repository_id, kind=kind, file_id=file_id, limit=limit, offset=offset
    )
    return [_to_symbol_response(s) for s in symbols]


@router.get("/symbols/{symbol_id}", response_model=SymbolResponse)
async def get_symbol(
    project_id: UUID,
    repository_id: UUID,
    symbol_id: UUID,
    service: ParsingService = Depends(get_parsing_service),
) -> SymbolResponse:
    """A single symbol, including its parameters and containing-class id."""
    symbol = await service.get_symbol(symbol_id)
    return _to_symbol_response(symbol)


@router.get("/parse-errors", response_model=list[ParseErrorResponse])
async def list_parse_errors(
    project_id: UUID,
    repository_id: UUID,
    service: ParsingService = Depends(get_parsing_service),
) -> list[ParseErrorResponse]:
    """Every recorded failure from this repository's most recent parse run —
    inspectable after the fact, not just in the `POST .../parse` response."""
    errors = await service.get_errors(repository_id)
    return [
        ParseErrorResponse(file_path=e.file_path, stage=e.stage, message=e.message)
        for e in errors
    ]


def _to_summary(result: ParseResult) -> ParseSummaryResponse:
    return ParseSummaryResponse(
        repository_id=result.repository_id,
        file_count=len(result.files),
        symbol_count=sum(len(f.symbols) for f in result.files),
        import_count=sum(len(f.imports) for f in result.files),
        error_count=len(result.errors),
        parsed_at=result.parsed_at,
    )


def _to_file_response(parsed_file: ParsedFileSummary) -> ParsedFileResponse:
    return ParsedFileResponse(
        id=parsed_file.id,
        repository_id=parsed_file.repository_id,
        path=parsed_file.path,
        language=parsed_file.language.value,
        has_syntax_errors=parsed_file.has_syntax_errors,
        symbol_count=parsed_file.symbol_count,
        import_count=parsed_file.import_count,
    )


def _to_symbol_response(symbol: Symbol) -> SymbolResponse:
    return SymbolResponse(
        id=symbol.id,
        kind=symbol.kind.value,
        name=symbol.name,
        qualified_name=symbol.qualified_name,
        start_line=symbol.location.start_line,
        end_line=symbol.location.end_line,
        start_column=symbol.location.start_column,
        end_column=symbol.location.end_column,
        parameters=[_to_parameter_response(p) for p in symbol.parameters],
        parent_symbol_id=symbol.parent_symbol_id,
    )


def _to_parameter_response(parameter: Parameter) -> ParameterResponse:
    return ParameterResponse(
        name=parameter.name,
        position=parameter.position,
        annotation=parameter.annotation,
        default_value=parameter.default_value,
    )
