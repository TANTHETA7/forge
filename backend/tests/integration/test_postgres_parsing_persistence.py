"""End-to-end test of SqlAlchemyParsedFileRepository against a REAL PostgreSQL
instance — not the in-memory fakes, for the same reason
test_postgres_persistence.py exists: a driver/schema-level defect (e.g. the
naive-vs-timezone-aware datetime bug already fixed once in Phase 2) only surfaces
against a real asyncpg connection.

Uses the shared `postgres_schema` fixture from tests/integration/conftest.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from forge.domain.parsing.entities import (
    CallReference,
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
from forge.domain.project.entities import Project, ProjectStatus
from forge.domain.repository.entities import (
    Repository,
    RepositorySourceType,
    RepositoryStatus,
)
from forge.infrastructure.persistence.parsed_file_repository_impl import (
    SqlAlchemyParsedFileRepository,
)
from forge.infrastructure.persistence.project_repository_impl import SqlAlchemyProjectRepository
from forge.infrastructure.persistence.repository_repository_impl import (
    SqlAlchemyRepositoryRepository,
)
from tests.integration.conftest import DSN_SQLALCHEMY


@pytest_asyncio.fixture
async def session(postgres_schema: None) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(DSN_SQLALCHEMY)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session_:
        yield session_
    await engine.dispose()


@pytest_asyncio.fixture
async def repository_id(session: AsyncSession) -> UUID:
    """`parsed_files.repository_id` (and symbols/imports/errors' own
    `repository_id`) is a real foreign key to `repositories.id` — parsing
    persistence tests need an actual `Project` + `Repository` row to reference,
    not a bare random UUID. Built via the existing Phase 2 repository
    implementations (reused, not duplicated) rather than hand-rolled INSERTs.
    """
    now = datetime.now(UTC)
    project = Project(
        id=uuid4(),
        name="Parsing Persistence Test Project",
        description=None,
        status=ProjectStatus.READY,
        created_at=now,
        updated_at=now,
    )
    await SqlAlchemyProjectRepository(session).create(project)

    repository = Repository(
        id=uuid4(),
        project_id=project.id,
        source_type=RepositorySourceType.ZIP,
        source_ref="fixture.zip",
        display_name="fixture",
        workspace_path="/tmp/does-not-matter-for-this-test",
        status=RepositoryStatus.READY,
        metadata=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    await SqlAlchemyRepositoryRepository(session).create(repository)
    return repository.id


def _sample_result(repository_id, file_path: str = "src/app.py") -> ParseResult:
    class_id = uuid4()
    method_id = uuid4()
    file_id = uuid4()

    class_symbol = Symbol(
        id=class_id,
        kind=SymbolKind.CLASS,
        name="Foo",
        qualified_name="Foo",
        location=SourceLocation(start_line=1, end_line=10, start_column=0, end_column=None),
        parameters=(),
        parent_symbol_id=None,
        base_class_names=("Base",),
    )
    method_symbol = Symbol(
        id=method_id,
        kind=SymbolKind.METHOD,
        name="bar",
        qualified_name="Foo.bar",
        location=SourceLocation(start_line=2, end_line=4, start_column=4, end_column=None),
        parameters=(
            Parameter(name="self", position=0, annotation=None, default_value=None),
            Parameter(name="x", position=1, annotation="int", default_value="1"),
        ),
        parent_symbol_id=class_id,
        calls=(
            CallReference(
                callee_expression="helper",
                location=SourceLocation(start_line=3, end_line=3, start_column=8, end_column=None),
            ),
        ),
    )
    import_ = Import(
        id=uuid4(),
        module="os",
        imported_names=(),
        alias=None,
        location=SourceLocation(start_line=1, end_line=1, start_column=0, end_column=None),
    )
    parsed_file = ParsedFile(
        id=file_id,
        repository_id=repository_id,
        path=file_path,
        language=Language.PYTHON,
        symbols=(class_symbol, method_symbol),
        imports=(import_,),
        has_syntax_errors=False,
    )
    return ParseResult(
        repository_id=repository_id,
        files=(parsed_file,),
        errors=(ParseError(file_path="broken.py", stage="parse", message="tree-sitter error"),),
        parsed_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_save_and_read_back_full_parse_result(
    session: AsyncSession, repository_id: UUID
) -> None:
    result = _sample_result(repository_id)

    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(result)

    files = await repo.get_files(repository_id)
    assert len(files) == 1
    assert files[0].path == "src/app.py"
    assert files[0].has_syntax_errors is False
    assert {s.name for s in files[0].symbols} == {"Foo", "bar"}
    assert files[0].imports[0].module == "os"


@pytest.mark.asyncio
async def test_base_class_names_round_trip(session: AsyncSession, repository_id: UUID) -> None:
    result = _sample_result(repository_id)
    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(result)

    symbols = await repo.get_symbols(repository_id)
    class_symbol = next(s for s in symbols if s.kind is SymbolKind.CLASS)
    method_symbol = next(s for s in symbols if s.kind is SymbolKind.METHOD)

    assert class_symbol.base_class_names == ("Base",)
    assert method_symbol.base_class_names == ()  # only CLASS rows carry this


@pytest.mark.asyncio
async def test_calls_round_trip(session: AsyncSession, repository_id: UUID) -> None:
    result = _sample_result(repository_id)
    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(result)

    symbols = await repo.get_symbols(repository_id)
    class_symbol = next(s for s in symbols if s.kind is SymbolKind.CLASS)
    method_symbol = next(s for s in symbols if s.kind is SymbolKind.METHOD)

    assert len(method_symbol.calls) == 1
    assert method_symbol.calls[0].callee_expression == "helper"
    assert method_symbol.calls[0].location.start_line == 3
    assert class_symbol.calls == ()  # only FUNCTION/METHOD rows carry this


@pytest.mark.asyncio
async def test_method_parent_symbol_id_round_trips(
    session: AsyncSession, repository_id: UUID
) -> None:
    result = _sample_result(repository_id)
    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(result)

    symbols = await repo.get_symbols(repository_id)
    class_symbol = next(s for s in symbols if s.kind is SymbolKind.CLASS)
    method_symbol = next(s for s in symbols if s.kind is SymbolKind.METHOD)

    assert method_symbol.parent_symbol_id == class_symbol.id


@pytest.mark.asyncio
async def test_parameters_round_trip_in_order(session: AsyncSession, repository_id: UUID) -> None:
    result = _sample_result(repository_id)
    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(result)

    method_symbol = next(
        s for s in await repo.get_symbols(repository_id) if s.kind is SymbolKind.METHOD
    )
    fetched = await repo.get_symbol(method_symbol.id)

    assert fetched is not None
    assert [p.name for p in fetched.parameters] == ["self", "x"]
    assert fetched.parameters[1].annotation == "int"
    assert fetched.parameters[1].default_value == "1"


@pytest.mark.asyncio
async def test_get_symbols_filters_by_kind(session: AsyncSession, repository_id: UUID) -> None:
    await SqlAlchemyParsedFileRepository(session).save_parse_result(_sample_result(repository_id))

    classes = await SqlAlchemyParsedFileRepository(session).get_symbols(
        repository_id, kind=SymbolKind.CLASS
    )
    assert len(classes) == 1
    assert classes[0].kind is SymbolKind.CLASS


@pytest.mark.asyncio
async def test_errors_round_trip(session: AsyncSession, repository_id: UUID) -> None:
    await SqlAlchemyParsedFileRepository(session).save_parse_result(_sample_result(repository_id))

    errors = await SqlAlchemyParsedFileRepository(session).get_errors(repository_id)
    assert len(errors) == 1
    assert errors[0].file_path == "broken.py"
    assert errors[0].stage == "parse"


@pytest.mark.asyncio
async def test_reparsing_replaces_previous_result(
    session: AsyncSession, repository_id: UUID
) -> None:
    repo = SqlAlchemyParsedFileRepository(session)

    await repo.save_parse_result(_sample_result(repository_id, file_path="v1.py"))
    await repo.save_parse_result(_sample_result(repository_id, file_path="v2.py"))

    files = await repo.get_files(repository_id)
    assert [f.path for f in files] == ["v2.py"]


@pytest.mark.asyncio
async def test_duplicate_symbol_names_in_different_files_persist_independently(
    session: AsyncSession, repository_id: UUID
) -> None:
    repo = SqlAlchemyParsedFileRepository(session)

    def _helper_file(path: str) -> ParsedFile:
        return ParsedFile(
            id=uuid4(),
            repository_id=repository_id,
            path=path,
            language=Language.PYTHON,
            symbols=(
                Symbol(
                    id=uuid4(),
                    kind=SymbolKind.FUNCTION,
                    name="helper",
                    qualified_name="helper",
                    location=SourceLocation(1, 2, 0, None),
                    parameters=(),
                    parent_symbol_id=None,
                ),
            ),
            imports=(),
            has_syntax_errors=False,
        )

    result = ParseResult(
        repository_id=repository_id,
        files=(_helper_file("a.py"), _helper_file("b.py")),
        errors=(),
        parsed_at=datetime.now(UTC),
    )
    await repo.save_parse_result(result)

    symbols = await repo.get_symbols(repository_id)
    assert len(symbols) == 2
    assert {s.name for s in symbols} == {"helper"}
    assert symbols[0].id != symbols[1].id
