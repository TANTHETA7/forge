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
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
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


@pytest.mark.asyncio
async def test_get_last_parsed_at_returns_none_before_any_parse(
    session: AsyncSession, repository_id: UUID
) -> None:
    """Added in Phase 6 (docs/architecture/06-code-intelligence.md, "Graph
    freshness") — exposes the already-stored `parsed_files.parsed_at` column
    through the domain port for the first time."""
    repo = SqlAlchemyParsedFileRepository(session)

    assert await repo.get_last_parsed_at(repository_id) is None


@pytest.mark.asyncio
async def test_get_last_parsed_at_returns_the_parse_timestamp(
    session: AsyncSession, repository_id: UUID
) -> None:
    repo = SqlAlchemyParsedFileRepository(session)
    result = _sample_result(repository_id)

    await repo.save_parse_result(result)

    last_parsed_at = await repo.get_last_parsed_at(repository_id)
    assert last_parsed_at is not None
    assert last_parsed_at == result.parsed_at


@pytest.mark.asyncio
async def test_get_last_parsed_at_reflects_the_most_recent_reparse(
    session: AsyncSession, repository_id: UUID
) -> None:
    repo = SqlAlchemyParsedFileRepository(session)
    first = _sample_result(repository_id)
    await repo.save_parse_result(first)

    second = ParseResult(
        repository_id=repository_id,
        files=first.files,
        errors=(),
        parsed_at=datetime.now(UTC),
    )
    await repo.save_parse_result(second)

    last_parsed_at = await repo.get_last_parsed_at(repository_id)
    assert last_parsed_at == second.parsed_at


# --- Large-scale / batched persistence -----------------------------------
#
# `save_parse_result` inserts symbols/parameters/call_sites/imports via
# chunked bulk `INSERT`s (`_INSERT_BATCH_SIZE = 500` rows per statement — see
# parsed_file_repository_impl.py's own docstring, "Persistence performance"),
# not one `Session.add()` per row. These tests are sized specifically to
# cross that 500-row boundary at least once (some cross it multiple times),
# so a regression that breaks chunk-boundary correctness (a dropped row, a
# duplicated row, or a foreign key pointing at a row from the wrong chunk)
# would actually be caught here — not just "the function was called".


def _many_top_level_functions(
    file_path: str, repository_id: UUID, count: int, *, calls_and_params_each: int = 1
) -> ParsedFile:
    """`count` distinct top-level FUNCTION symbols, each with
    `calls_and_params_each` parameters and `calls_and_params_each` calls —
    used to drive the symbols/parameters/call_sites tables past one or more
    500-row batch boundaries."""
    symbols = tuple(
        Symbol(
            id=uuid4(),
            kind=SymbolKind.FUNCTION,
            name=f"func_{i}",
            qualified_name=f"func_{i}",
            location=SourceLocation(start_line=i, end_line=i + 1, start_column=0, end_column=None),
            parameters=tuple(
                Parameter(name=f"p{j}", position=j, annotation=None, default_value=None)
                for j in range(calls_and_params_each)
            ),
            parent_symbol_id=None,
            calls=tuple(
                CallReference(
                    callee_expression=f"callee_{i}_{j}",
                    location=SourceLocation(
                        start_line=i, end_line=i, start_column=j, end_column=None
                    ),
                )
                for j in range(calls_and_params_each)
            ),
        )
        for i in range(count)
    )
    return ParsedFile(
        id=uuid4(),
        repository_id=repository_id,
        path=file_path,
        language=Language.PYTHON,
        symbols=symbols,
        imports=(),
        has_syntax_errors=False,
    )


@pytest.mark.asyncio
async def test_large_symbol_set_persists_correctly_across_multiple_batches(
    session: AsyncSession, repository_id: UUID
) -> None:
    # 1,300 symbols, each with 2 parameters and 2 calls, spans 3 insert
    # batches for symbols (500+500+300) and calls/parameters
    # (500+500+500+300+300 -> more batches still, since there are 2,600 of
    # each) — a genuinely multi-batch write, not a single-statement one.
    count = 1300
    per_symbol = 2
    parsed_file = _many_top_level_functions(
        "big.py", repository_id, count, calls_and_params_each=per_symbol
    )
    result = ParseResult(
        repository_id=repository_id, files=(parsed_file,), errors=(), parsed_at=datetime.now(UTC)
    )

    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(result)

    symbols = await repo.get_symbols(repository_id, limit=count + 100)
    assert len(symbols) == count  # none lost, none duplicated across batches
    assert len({s.id for s in symbols}) == count  # every id distinct

    # Deterministic ids pass through the bulk-insert path unchanged.
    expected_ids = {s.id for s in parsed_file.symbols}
    assert {s.id for s in symbols} == expected_ids

    # Spot-check one symbol from each batch: first row, last row of batch 1
    # (index 499, the 500-row boundary itself), first row of batch 2 (index
    # 500), and the last row overall (index 1299).
    by_name = {s.name: s for s in symbols}
    for i in (0, 499, 500, 999, 1000, count - 1):
        symbol = by_name[f"func_{i}"]
        assert len(symbol.parameters) == per_symbol
        assert len(symbol.calls) == per_symbol
        # Set, not index/order: `call_sites` has no `start_column` (see
        # models.py's `CallSiteRow`) — same `start_line` calls have no
        # persisted ordering between them, so positional order isn't a real
        # guarantee this test should assume.
        assert {c.callee_expression for c in symbol.calls} == {
            f"callee_{i}_{j}" for j in range(per_symbol)
        }

    total_params = sum(len(s.parameters) for s in symbols)
    total_calls = sum(len(s.calls) for s in symbols)
    assert total_params == count * per_symbol
    assert total_calls == count * per_symbol


@pytest.mark.asyncio
async def test_calls_sharing_a_start_line_have_no_source_order_but_are_read_deterministically(
    session: AsyncSession, repository_id: UUID
) -> None:
    # Documents the actual ordering contract for `Symbol.calls`, explicitly:
    # `call_sites` has no `start_column` column (see models.py's
    # `CallSiteRow`), so when multiple calls share the same `start_line` —
    # a real, common case — there is no stored data anywhere that encodes
    # which one appeared first in the source. This is not a limitation
    # introduced by batching `_calls_for_many`: the single-symbol
    # `_calls_for` query has exactly the same gap, and always did — a prior
    # test's assumption that call 0 always comes back first
    # (test_large_symbol_set_persists_correctly_across_multiple_batches) was
    # relying on incidental physical row order for a tiny single-symbol
    # query, not a real guarantee, which is why it broke under the batched
    # multi-symbol query shape without any data being lost or corrupted.
    #
    # What *is* guaranteed, and is what this test actually locks in: reading
    # the same persisted data back twice returns calls in the exact same
    # (if source-arbitrary) order both times — the `.id` tiebreaker added
    # alongside `start_line` in `_calls_for`/`_calls_for_many`'s `ORDER BY`
    # is what makes that true; without it, two reads of a tied `start_line`
    # could legitimately disagree with each other.
    symbol = Symbol(
        id=uuid4(),
        kind=SymbolKind.FUNCTION,
        name="many_calls_one_line",
        qualified_name="many_calls_one_line",
        location=SourceLocation(start_line=1, end_line=2, start_column=0, end_column=None),
        parameters=(),
        parent_symbol_id=None,
        calls=tuple(
            CallReference(
                callee_expression=f"callee_{j}",
                location=SourceLocation(
                    start_line=10, end_line=10, start_column=j, end_column=None
                ),
            )
            for j in range(5)
        ),
    )
    parsed_file = ParsedFile(
        id=uuid4(),
        repository_id=repository_id,
        path="tied_calls.py",
        language=Language.PYTHON,
        symbols=(symbol,),
        imports=(),
        has_syntax_errors=False,
    )
    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(
        ParseResult(
            repository_id=repository_id,
            files=(parsed_file,),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )

    first_read = await repo.get_symbol(symbol.id)
    second_read = await repo.get_symbol(symbol.id)
    assert first_read is not None
    assert second_read is not None

    # No data loss: every call site persisted, regardless of order.
    assert {c.callee_expression for c in first_read.calls} == {f"callee_{j}" for j in range(5)}

    # Deterministic across reads: not necessarily source order, but the
    # exact same order every time — proves the `.id` tiebreaker is doing its
    # job, not just that the data happens to be present.
    assert [c.callee_expression for c in first_read.calls] == [
        c.callee_expression for c in second_read.calls
    ]

    # Same contract holds through get_symbols (the batched, multi-symbol
    # path `_calls_for_many` uses), not just get_symbol (the single-symbol
    # `_calls_for` path).
    [via_get_symbols] = await repo.get_symbols(repository_id, limit=10)
    assert [c.callee_expression for c in via_get_symbols.calls] == [
        c.callee_expression for c in first_read.calls
    ]


@pytest.mark.asyncio
async def test_large_import_set_persists_correctly_across_multiple_batches(
    session: AsyncSession, repository_id: UUID
) -> None:
    # 650 imports in one file crosses the 500-row batch boundary once.
    count = 650
    file_id = uuid4()
    imports = tuple(
        Import(
            id=uuid4(),
            module=f"pkg.mod_{i}",
            imported_names=(),
            alias=None,
            location=SourceLocation(start_line=i, end_line=i, start_column=0, end_column=None),
        )
        for i in range(count)
    )
    parsed_file = ParsedFile(
        id=file_id,
        repository_id=repository_id,
        path="many_imports.py",
        language=Language.PYTHON,
        symbols=(),
        imports=imports,
        has_syntax_errors=False,
    )
    result = ParseResult(
        repository_id=repository_id, files=(parsed_file,), errors=(), parsed_at=datetime.now(UTC)
    )

    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(result)

    files = await repo.get_files(repository_id)
    assert len(files) == 1
    assert len(files[0].imports) == count
    assert len({i.id for i in files[0].imports}) == count  # no duplicates across batches
    assert {i.module for i in files[0].imports} == {f"pkg.mod_{i}" for i in range(count)}


@pytest.mark.asyncio
async def test_self_referential_parent_child_across_a_batch_boundary_still_links_correctly(
    session: AsyncSession, repository_id: UUID
) -> None:
    # The trickiest correctness risk in chunked bulk-inserting a
    # self-referential table: a CLASS symbol placed as the very LAST row of
    # batch 1 (index 499) and its METHOD child as the very FIRST row of
    # batch 2 (index 500). If chunk ordering or chunk-sequencing were wrong,
    # this specific arrangement is exactly what would surface it — either as
    # a foreign key violation (parent not yet visible) or a silently
    # unresolved parent_symbol_id.
    padding_before = 499
    padding_after = 50
    class_id = uuid4()
    method_id = uuid4()
    file_id = uuid4()

    symbols = []
    for i in range(padding_before):
        symbols.append(
            Symbol(
                id=uuid4(),
                kind=SymbolKind.FUNCTION,
                name=f"pad_before_{i}",
                qualified_name=f"pad_before_{i}",
                location=SourceLocation(i, i + 1, 0, None),
                parameters=(),
                parent_symbol_id=None,
            )
        )
    symbols.append(  # index 499 — last row of batch 1
        Symbol(
            id=class_id,
            kind=SymbolKind.CLASS,
            name="BoundaryClass",
            qualified_name="BoundaryClass",
            location=SourceLocation(600, 700, 0, None),
            parameters=(),
            parent_symbol_id=None,
        )
    )
    symbols.append(  # index 500 — first row of batch 2
        Symbol(
            id=method_id,
            kind=SymbolKind.METHOD,
            name="boundary_method",
            qualified_name="BoundaryClass.boundary_method",
            location=SourceLocation(601, 602, 4, None),
            parameters=(),
            parent_symbol_id=class_id,
        )
    )
    for i in range(padding_after):
        symbols.append(
            Symbol(
                id=uuid4(),
                kind=SymbolKind.FUNCTION,
                name=f"pad_after_{i}",
                qualified_name=f"pad_after_{i}",
                location=SourceLocation(800 + i, 800 + i + 1, 0, None),
                parameters=(),
                parent_symbol_id=None,
            )
        )

    parsed_file = ParsedFile(
        id=file_id,
        repository_id=repository_id,
        path="boundary.py",
        language=Language.PYTHON,
        symbols=tuple(symbols),
        imports=(),
        has_syntax_errors=False,
    )
    result = ParseResult(
        repository_id=repository_id, files=(parsed_file,), errors=(), parsed_at=datetime.now(UTC)
    )

    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(result)  # must not raise a foreign-key violation

    fetched_method = await repo.get_symbol(method_id)
    assert fetched_method is not None
    assert fetched_method.parent_symbol_id == class_id

    all_symbols = await repo.get_symbols(repository_id, limit=len(symbols) + 10)
    assert len(all_symbols) == len(symbols)


@pytest.mark.asyncio
async def test_empty_parse_result_persists_without_error(
    session: AsyncSession, repository_id: UUID
) -> None:
    result = ParseResult(
        repository_id=repository_id, files=(), errors=(), parsed_at=datetime.now(UTC)
    )
    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(result)  # must not raise on empty batches

    assert await repo.get_files(repository_id) == []


@pytest.mark.asyncio
async def test_file_with_no_symbols_or_imports_persists_without_error(
    session: AsyncSession, repository_id: UUID
) -> None:
    parsed_file = ParsedFile(
        id=uuid4(),
        repository_id=repository_id,
        path="empty.py",
        language=Language.PYTHON,
        symbols=(),
        imports=(),
        has_syntax_errors=False,
    )
    result = ParseResult(
        repository_id=repository_id, files=(parsed_file,), errors=(), parsed_at=datetime.now(UTC)
    )
    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(result)  # must not raise on empty parameter/call/import batches

    files = await repo.get_files(repository_id)
    assert len(files) == 1
    assert files[0].symbols == ()
    assert files[0].imports == ()


@pytest.mark.asyncio
async def test_large_reparse_fully_replaces_the_previous_large_result(
    session: AsyncSession, repository_id: UUID
) -> None:
    repo = SqlAlchemyParsedFileRepository(session)

    first_count = 600
    first_file = _many_top_level_functions("v1.py", repository_id, first_count)
    await repo.save_parse_result(
        ParseResult(
            repository_id=repository_id,
            files=(first_file,),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )

    second_count = 700
    second_file = _many_top_level_functions("v2.py", repository_id, second_count)
    await repo.save_parse_result(
        ParseResult(
            repository_id=repository_id,
            files=(second_file,),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )

    files = await repo.get_files(repository_id)
    assert [f.path for f in files] == ["v2.py"]  # v1 fully gone, not merged

    symbols = await repo.get_symbols(repository_id, limit=second_count + 100)
    assert len(symbols) == second_count  # exactly the second result's count — no leftovers


@pytest.mark.asyncio
async def test_a_foreign_key_violation_rolls_back_the_entire_result_not_just_the_failing_batch(
    session: AsyncSession, repository_id: UUID
) -> None:
    # A symbol whose parent_symbol_id references a UUID that was never
    # inserted anywhere violates SymbolRow's self-referential foreign key —
    # this must fail the whole `save_parse_result` call, and none of the
    # already-*executed*-but-not-yet-*committed* earlier stages (the
    # parsed_files row, in this case) may survive as a visible result.
    parsed_file = ParsedFile(
        id=uuid4(),
        repository_id=repository_id,
        path="bad.py",
        language=Language.PYTHON,
        symbols=(
            Symbol(
                id=uuid4(),
                kind=SymbolKind.METHOD,
                name="orphan_method",
                qualified_name="orphan_method",
                location=SourceLocation(1, 2, 0, None),
                parameters=(),
                parent_symbol_id=uuid4(),  # does not exist anywhere -> FK violation
            ),
        ),
        imports=(),
        has_syntax_errors=False,
    )
    result = ParseResult(
        repository_id=repository_id, files=(parsed_file,), errors=(), parsed_at=datetime.now(UTC)
    )

    repo = SqlAlchemyParsedFileRepository(session)
    with pytest.raises(DBAPIError):  # the real foreign-key violation from Postgres
        await repo.save_parse_result(result)
    await session.rollback()

    # A fresh repository instance on the same (now rolled-back) session sees
    # nothing — not even the parsed_files row that was sent to Postgres
    # before the symbols stage failed.
    assert await SqlAlchemyParsedFileRepository(session).get_files(repository_id) == []


@pytest.mark.asyncio
async def test_get_symbols_pagination_is_stable_when_many_symbols_share_a_start_line(
    session: AsyncSession, repository_id: UUID
) -> None:
    # Regression test for a real bug found validating Forge against
    # pytest-dev/pytest (270 files): `get_symbols` ordered only by
    # `start_line`, a column that ties heavily on a real repository (many
    # symbols across different files start on the same line number).
    # PostgreSQL gives no guarantee that `LIMIT`/`OFFSET` sees the same
    # tie-order across two separate query executions, so paginating this
    # endpoint end-to-end (as `GET /symbols` clients, and any future internal
    # consumer, must) could silently duplicate a symbol across two pages
    # while dropping another entirely. Every symbol here shares the exact
    # same `start_line`, forcing every page boundary to fall inside a tie —
    # exactly the condition that reproduces the bug.
    count = 1300
    page_size = 500
    symbols = tuple(
        Symbol(
            id=uuid4(),
            kind=SymbolKind.FUNCTION,
            name=f"func_{i}",
            qualified_name=f"func_{i}",
            location=SourceLocation(start_line=1, end_line=2, start_column=0, end_column=None),
            parameters=(),
            parent_symbol_id=None,
        )
        for i in range(count)
    )
    parsed_file = ParsedFile(
        id=uuid4(),
        repository_id=repository_id,
        path="tied.py",
        language=Language.PYTHON,
        symbols=symbols,
        imports=(),
        has_syntax_errors=False,
    )
    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(
        ParseResult(
            repository_id=repository_id,
            files=(parsed_file,),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )

    drained: list[Symbol] = []
    offset = 0
    while True:
        page = await repo.get_symbols(repository_id, limit=page_size, offset=offset)
        drained.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    assert len(drained) == count  # none dropped, none duplicated across the page boundary
    assert len({s.id for s in drained}) == count
    assert {s.id for s in drained} == {s.id for s in symbols}


@pytest.mark.asyncio
async def test_get_files_and_get_symbols_issue_a_bounded_number_of_queries_regardless_of_size(
    session: AsyncSession, repository_id: UUID
) -> None:
    # Regression test for a real, severe bug found validating Forge against
    # matplotlib/matplotlib (914 files, 12,256 symbols): `get_files` fetched
    # each file's symbols, then each *symbol's* parameters and calls, one
    # query at a time — roughly 1 + files + 2×symbols + files round trips for
    # one call (≈26,000 for matplotlib's scale) — and
    # `GraphService.project_repository` (application/graph/service.py) calls
    # exactly this method first, so *every* graph projection paid this cost
    # too (on a real run, this surfaced as ~35 minutes for what should have
    # been a few seconds). A query-count assertion, not a wall-clock timing
    # one: no flakiness risk, and it directly encodes the regression — a
    # batched implementation's query count stays constant regardless of
    # file/symbol count, where the N+1 version's grows linearly with it.
    file_count = 20
    symbols_per_file = 15
    files = tuple(
        _many_top_level_functions(f"file_{i}.py", repository_id, symbols_per_file)
        for i in range(file_count)
    )
    repo = SqlAlchemyParsedFileRepository(session)
    await repo.save_parse_result(
        ParseResult(
            repository_id=repository_id, files=files, errors=(), parsed_at=datetime.now(UTC)
        )
    )

    query_count = 0

    def _count_query(*_args: object, **_kwargs: object) -> None:
        nonlocal query_count
        query_count += 1

    event.listen(Engine, "before_cursor_execute", _count_query)
    try:
        result_files = await repo.get_files(repository_id)
        assert len(result_files) == file_count
        assert sum(len(f.symbols) for f in result_files) == file_count * symbols_per_file

        query_count_for_get_files = query_count
        query_count = 0
        result_symbols = await repo.get_symbols(
            repository_id, limit=file_count * symbols_per_file + 10
        )
        assert len(result_symbols) == file_count * symbols_per_file
    finally:
        event.remove(Engine, "before_cursor_execute", _count_query)

    # A handful of queries (files/symbols/parameters/calls, or symbols/
    # parameters/calls) — nowhere near the 300+ an N+1 pattern would need at
    # this file/symbol count, and completely independent of it.
    assert query_count_for_get_files < 10
    assert query_count < 10
