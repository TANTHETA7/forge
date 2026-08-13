"""End-to-end test of SqlAlchemyDependencyEdgeRepository against a REAL
PostgreSQL instance — not the in-memory fakes, for the same reason Phase 3's
equivalent test exists: FK/cascade behavior only surfaces against a real
asyncpg connection.

Uses the shared `postgres_schema` fixture from tests/integration/conftest.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from forge.domain.dependency_analysis.entities import (
    DependencyEdge,
    DependencyKind,
    ResolutionStatus,
)
from forge.domain.parsing.entities import (
    Language,
    ParsedFile,
    ParseResult,
    SourceLocation,
    Symbol,
    SymbolKind,
)
from forge.domain.project.entities import Project, ProjectStatus
from forge.domain.repository.entities import Repository, RepositorySourceType, RepositoryStatus
from forge.infrastructure.persistence.dependency_edge_repository_impl import (
    SqlAlchemyDependencyEdgeRepository,
)
from forge.infrastructure.persistence.models import ParsedFileRow
from forge.infrastructure.persistence.parsed_file_repository_impl import (
    SqlAlchemyParsedFileRepository,
)
from forge.infrastructure.persistence.project_repository_impl import SqlAlchemyProjectRepository
from forge.infrastructure.persistence.repository_repository_impl import (
    SqlAlchemyRepositoryRepository,
)
from tests.integration.conftest import DSN_SQLALCHEMY

_LOCATION = SourceLocation(start_line=1, end_line=1, start_column=0, end_column=None)


@pytest_asyncio.fixture
async def session(postgres_schema: None) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(DSN_SQLALCHEMY)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session_:
        yield session_
    await engine.dispose()


@pytest_asyncio.fixture
async def parsed_repository(session: AsyncSession) -> tuple[UUID, UUID, UUID]:
    """Seeds a real Project -> Repository -> ParsedFile (with one FUNCTION
    symbol) -> so dependency_edges' foreign keys have something real to
    reference. Returns (repository_id, file_id, symbol_id)."""
    now = datetime.now(UTC)
    project = Project(
        id=uuid4(),
        name="Dependency Persistence Test",
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
        workspace_path="/tmp/does-not-matter",
        status=RepositoryStatus.READY,
        metadata=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    await SqlAlchemyRepositoryRepository(session).create(repository)

    symbol = Symbol(
        id=uuid4(),
        kind=SymbolKind.FUNCTION,
        name="helper",
        qualified_name="helper",
        location=_LOCATION,
        parameters=(),
        parent_symbol_id=None,
    )
    parsed_file = ParsedFile(
        id=uuid4(),
        repository_id=repository.id,
        path="a.py",
        language=Language.PYTHON,
        symbols=(symbol,),
        imports=(),
        has_syntax_errors=False,
    )
    await SqlAlchemyParsedFileRepository(session).save_parse_result(
        ParseResult(repository_id=repository.id, files=(parsed_file,), errors=(), parsed_at=now)
    )
    return repository.id, parsed_file.id, symbol.id


def _edge(
    repository_id: UUID,
    file_id: UUID,
    *,
    kind: DependencyKind = DependencyKind.IMPORTS,
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
    target_file_id: UUID | None = None,
    raw: str = "some.module",
) -> DependencyEdge:
    return DependencyEdge(
        id=uuid4(),
        repository_id=repository_id,
        kind=kind,
        resolution_status=status,
        source_file_id=file_id,
        source_symbol_id=None,
        target_file_id=target_file_id,
        target_symbol_id=None,
        raw_target_expression=raw,
        location=_LOCATION,
        detail=None if status is ResolutionStatus.RESOLVED else "not found",
    )


async def test_save_and_read_back_edges(
    session: AsyncSession, parsed_repository: tuple[UUID, UUID, UUID]
) -> None:
    repository_id, file_id, _symbol_id = parsed_repository
    repo = SqlAlchemyDependencyEdgeRepository(session)
    edge = _edge(repository_id, file_id, target_file_id=file_id, raw="a")

    await repo.save_analysis_result(repository_id, (edge,))

    edges = await repo.get_edges(repository_id)
    assert len(edges) == 1
    assert edges[0].id == edge.id
    assert edges[0].kind is DependencyKind.IMPORTS
    assert edges[0].resolution_status is ResolutionStatus.RESOLVED
    assert edges[0].target_file_id == file_id


async def test_unresolved_edge_has_no_target_but_has_detail(
    session: AsyncSession, parsed_repository: tuple[UUID, UUID, UUID]
) -> None:
    repository_id, file_id, _ = parsed_repository
    repo = SqlAlchemyDependencyEdgeRepository(session)
    edge = _edge(repository_id, file_id, status=ResolutionStatus.UNRESOLVED, raw="external_pkg")

    await repo.save_analysis_result(repository_id, (edge,))

    [fetched] = await repo.get_edges(repository_id)
    assert fetched.resolution_status is ResolutionStatus.UNRESOLVED
    assert fetched.target_file_id is None
    assert fetched.detail == "not found"


async def test_get_edges_filters_by_kind_and_status(
    session: AsyncSession, parsed_repository: tuple[UUID, UUID, UUID]
) -> None:
    repository_id, file_id, _ = parsed_repository
    repo = SqlAlchemyDependencyEdgeRepository(session)
    resolved = _edge(repository_id, file_id, target_file_id=file_id, raw="a")
    unresolved = _edge(repository_id, file_id, status=ResolutionStatus.UNRESOLVED, raw="b")
    await repo.save_analysis_result(repository_id, (resolved, unresolved))

    only_resolved = await repo.get_edges(repository_id, resolution_status=ResolutionStatus.RESOLVED)
    assert [e.id for e in only_resolved] == [resolved.id]

    only_imports = await repo.get_edges(repository_id, kind=DependencyKind.IMPORTS)
    assert len(only_imports) == 2


async def test_get_edge_by_id(
    session: AsyncSession, parsed_repository: tuple[UUID, UUID, UUID]
) -> None:
    repository_id, file_id, _ = parsed_repository
    repo = SqlAlchemyDependencyEdgeRepository(session)
    edge = _edge(repository_id, file_id, target_file_id=file_id, raw="a")
    await repo.save_analysis_result(repository_id, (edge,))

    fetched = await repo.get_edge(edge.id)
    assert fetched is not None
    assert fetched.id == edge.id

    assert await repo.get_edge(UUID(int=0)) is None


async def test_reanalysis_is_idempotent_and_replaces_previous_edges(
    session: AsyncSession, parsed_repository: tuple[UUID, UUID, UUID]
) -> None:
    repository_id, file_id, _ = parsed_repository
    repo = SqlAlchemyDependencyEdgeRepository(session)
    first_run = (_edge(repository_id, file_id, target_file_id=file_id, raw="a"),)

    await repo.save_analysis_result(repository_id, first_run)
    await repo.save_analysis_result(repository_id, first_run)  # re-run, identical input

    edges = await repo.get_edges(repository_id)
    assert len(edges) == 1
    assert edges[0].id == first_run[0].id  # same deterministic id, not duplicated


async def test_deleting_parsed_file_cascades_to_dependency_edges(
    session: AsyncSession, parsed_repository: tuple[UUID, UUID, UUID]
) -> None:
    repository_id, file_id, _ = parsed_repository
    repo = SqlAlchemyDependencyEdgeRepository(session)
    edge = _edge(repository_id, file_id, target_file_id=file_id, raw="a")
    await repo.save_analysis_result(repository_id, (edge,))

    # Simulate a Phase 3 re-parse: delete the parsed_files row directly.
    await session.execute(delete(ParsedFileRow).where(ParsedFileRow.id == file_id))
    await session.commit()

    assert await repo.get_edges(repository_id) == []


async def test_large_edge_set_persists_correctly_across_multiple_insert_batches(
    session: AsyncSession, parsed_repository: tuple[UUID, UUID, UUID]
) -> None:
    # Regression test for a real bug found validating Forge against
    # pytest-dev/pytest (270 files, 28,755 dependency edges): edges were
    # inserted one `Session.add()` at a time — the same anti-pattern already
    # fixed for `SqlAlchemyParsedFileRepository.save_parse_result` — making
    # persisting a real repository's dependency analysis far slower than the
    # chunked bulk-insert form. 1,300 edges spans 3 insert batches
    # (500+500+300) at `_INSERT_BATCH_SIZE = 500`.
    repository_id, file_id, _symbol_id = parsed_repository
    repo = SqlAlchemyDependencyEdgeRepository(session)
    count = 1300
    edges = tuple(
        _edge(repository_id, file_id, target_file_id=file_id, raw=f"mod_{i}") for i in range(count)
    )

    await repo.save_analysis_result(repository_id, edges)

    fetched = await repo.get_edges(repository_id, limit=count + 100)
    assert len(fetched) == count  # none lost, none duplicated across batches
    assert len({e.id for e in fetched}) == count  # every id distinct
    assert {e.id for e in fetched} == {e.id for e in edges}  # deterministic ids pass through


async def test_get_edges_pagination_is_stable_when_many_edges_share_a_start_line(
    session: AsyncSession, parsed_repository: tuple[UUID, UUID, UUID]
) -> None:
    # Regression test for a real bug found validating Forge against
    # pytest-dev/pytest: `get_edges` ordered only by `start_line`, a column
    # that ties heavily on a real repository (28,755 edges over only 3,301
    # distinct `start_line` values there). PostgreSQL gives no guarantee that
    # `LIMIT`/`OFFSET` sees the same tie-order across two separate query
    # executions — `application/graph/service.py`'s `_load_all_edges` drains
    # this exact method to build every graph projection, so an unstable page
    # boundary here silently corrupts the projected graph's relationship set,
    # not just `GET /dependencies` API pagination. Every edge here shares the
    # exact same `start_line`, forcing every page boundary to fall inside a
    # tie — exactly the condition that reproduces the bug.
    repository_id, file_id, _symbol_id = parsed_repository
    repo = SqlAlchemyDependencyEdgeRepository(session)
    count = 1300
    page_size = 500
    edges = tuple(
        _edge(repository_id, file_id, target_file_id=file_id, raw=f"mod_{i}") for i in range(count)
    )
    await repo.save_analysis_result(repository_id, edges)

    drained: list[DependencyEdge] = []
    offset = 0
    while True:
        page = await repo.get_edges(repository_id, limit=page_size, offset=offset)
        drained.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    assert len(drained) == count  # none dropped, none duplicated across the page boundary
    assert len({e.id for e in drained}) == count
    assert {e.id for e in drained} == {e.id for e in edges}
