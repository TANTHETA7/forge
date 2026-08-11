"""Orchestration tests for DependencyAnalysisService.

Exercises the full workflow — repository lookup, loading parsed files, module
resolution, persistence — against the real `PythonModuleResolver` but in-memory
fakes for persistence (see tests/fakes.py), mirroring test_parsing_service.py's
established approach: real everything except the database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from forge.application.dependency_analysis.service import DependencyAnalysisService
from forge.domain.dependency_analysis.entities import ResolutionStatus
from forge.domain.dependency_analysis.ports import ModuleResolution
from forge.domain.errors import NotFoundError, UnsupportedRepositoryStateError
from forge.domain.parsing.entities import (
    CallReference,
    Import,
    Language,
    ParsedFile,
    ParseResult,
    SourceLocation,
    Symbol,
    SymbolKind,
)
from forge.domain.repository.entities import Repository, RepositorySourceType, RepositoryStatus
from forge.infrastructure.dependency_analysis.python_module_resolver import PythonModuleResolver
from forge.infrastructure.dependency_analysis.symbol_dependency_resolver import (
    SymbolDependencyResolver,
)
from tests.fakes import (
    InMemoryDependencyEdgeRepository,
    InMemoryParsedFileRepository,
    InMemoryRepositoryRepository,
)

_LOCATION = SourceLocation(start_line=1, end_line=1, start_column=0, end_column=None)


def _service() -> tuple[
    DependencyAnalysisService,
    InMemoryRepositoryRepository,
    InMemoryParsedFileRepository,
    InMemoryDependencyEdgeRepository,
]:
    repositories = InMemoryRepositoryRepository()
    parsed_files = InMemoryParsedFileRepository()
    dependency_edges = InMemoryDependencyEdgeRepository()
    module_resolver = PythonModuleResolver()
    service = DependencyAnalysisService(
        repositories=repositories,
        parsed_files=parsed_files,
        dependency_edges=dependency_edges,
        module_resolver=module_resolver,
        symbol_resolver=SymbolDependencyResolver(module_resolver),
    )
    return service, repositories, parsed_files, dependency_edges


async def _seed_ready_repository(
    repositories: InMemoryRepositoryRepository, *, status: RepositoryStatus = RepositoryStatus.READY
) -> Repository:
    now = datetime.now(UTC)
    repository = Repository(
        id=uuid4(),
        project_id=uuid4(),
        source_type=RepositorySourceType.ZIP,
        source_ref="upload.zip",
        display_name="upload",
        workspace_path="/tmp/does-not-matter",
        status=status,
        metadata=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    await repositories.create(repository)
    return repository


def _python_file(
    path: str, imports: tuple[Import, ...] = (), symbols: tuple[Symbol, ...] = ()
) -> ParsedFile:
    return ParsedFile(
        id=uuid4(),
        repository_id=uuid4(),
        path=path,
        language=Language.PYTHON,
        symbols=symbols,
        imports=imports,
        has_syntax_errors=False,
    )


async def test_resolves_a_relative_import_between_two_files() -> None:
    service, repositories, parsed_files, dependency_edges = _service()
    repository = await _seed_ready_repository(repositories)

    utils_file = _python_file("pkg/utils.py")
    main_file = _python_file(
        "pkg/main.py",
        imports=(
            Import(id=uuid4(), module=".utils", imported_names=(), alias=None, location=_LOCATION),
        ),
    )
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(main_file, utils_file),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )

    result = await service.analyze_repository(repository.id)

    assert len(result.edges) == 1
    edge = result.edges[0]
    assert edge.resolution_status is ResolutionStatus.RESOLVED
    assert edge.target_file_id == utils_file.id
    assert edge.source_file_id == main_file.id

    # Persisted, not just returned:
    persisted = await dependency_edges.get_edges(repository.id)
    assert len(persisted) == 1


async def test_external_import_is_unresolved_not_an_error() -> None:
    service, repositories, parsed_files, _ = _service()
    repository = await _seed_ready_repository(repositories)
    main_file = _python_file(
        "main.py",
        imports=(
            Import(id=uuid4(), module="numpy", imported_names=(), alias=None, location=_LOCATION),
        ),
    )
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id, files=(main_file,), errors=(), parsed_at=datetime.now(UTC)
        )
    )

    result = await service.analyze_repository(repository.id)

    assert result.edges[0].resolution_status is ResolutionStatus.UNRESOLVED
    assert result.edges[0].target_file_id is None
    assert result.edges[0].detail is not None


async def test_resolver_exception_degrades_to_unresolved_and_does_not_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, repositories, parsed_files, _ = _service()
    repository = await _seed_ready_repository(repositories)
    main_file = _python_file(
        "main.py",
        imports=(
            Import(id=uuid4(), module=".a", imported_names=(), alias=None, location=_LOCATION),
            Import(
                id=uuid4(),
                module=".b",
                imported_names=(),
                alias=None,
                location=SourceLocation(2, 2, 0, None),
            ),
        ),
    )
    other_file = _python_file("b.py")
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(main_file, other_file),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )

    def _always_raises(self: object, **kwargs: object) -> ModuleResolution:
        raise RuntimeError("simulated resolver bug")

    monkeypatch.setattr(PythonModuleResolver, "resolve_import", _always_raises)

    result = await service.analyze_repository(repository.id)

    # Both imports still produce edges (neither aborts the other), both
    # degraded to UNRESOLVED since the resolver itself is broken in this test.
    assert len(result.edges) == 2
    assert all(e.resolution_status is ResolutionStatus.UNRESOLVED for e in result.edges)


async def test_analyzing_unknown_repository_raises_not_found() -> None:
    service, _repositories, _parsed_files, _ = _service()
    with pytest.raises(NotFoundError):
        await service.analyze_repository(uuid4())


async def test_analyzing_non_ready_repository_is_rejected() -> None:
    service, repositories, _parsed_files, _ = _service()
    repository = await _seed_ready_repository(repositories, status=RepositoryStatus.IMPORTING)
    with pytest.raises(UnsupportedRepositoryStateError):
        await service.analyze_repository(repository.id)


async def test_analyzing_unparsed_repository_is_rejected() -> None:
    service, repositories, _parsed_files, _ = _service()
    repository = await _seed_ready_repository(repositories)  # READY, but never parsed
    with pytest.raises(UnsupportedRepositoryStateError):
        await service.analyze_repository(repository.id)


async def test_reanalysis_replaces_previous_edges() -> None:
    service, repositories, parsed_files, dependency_edges = _service()
    repository = await _seed_ready_repository(repositories)
    utils_file = _python_file("utils.py")
    main_file = _python_file(
        "main.py",
        imports=(
            Import(id=uuid4(), module=".utils", imported_names=(), alias=None, location=_LOCATION),
        ),
    )
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(main_file, utils_file),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )

    first = await service.analyze_repository(repository.id)
    second = await service.analyze_repository(repository.id)

    assert first.edges[0].id == second.edges[0].id  # deterministic
    persisted = await dependency_edges.get_edges(repository.id)
    assert len(persisted) == 1  # not duplicated


async def test_two_identical_imports_at_an_identical_location_get_distinct_edge_ids() -> None:
    # The edge id is derived from repository/source_file/module-text/location
    # — all of which are identical between two occurrences of the exact same
    # import statement repeated verbatim (a real, if unusual, source pattern,
    # and a stand-in for any parser quirk that reports an identical location
    # for two distinct occurrences). Without `occurrence_index` — this
    # import's own ordinal position within `source_file.imports`, guaranteed
    # to differ between the two — both would hash to the *same* id and
    # silently collapse into a single persisted edge.
    service, repositories, parsed_files, _ = _service()
    repository = await _seed_ready_repository(repositories)

    utils_file = _python_file("pkg/utils.py")
    main_file = _python_file(
        "pkg/main.py",
        imports=(
            Import(
                id=uuid4(), module=".utils", imported_names=(), alias=None, location=_LOCATION
            ),
            Import(
                id=uuid4(), module=".utils", imported_names=(), alias=None, location=_LOCATION
            ),
        ),
    )
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(main_file, utils_file),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )

    result = await service.analyze_repository(repository.id)

    import_edges = [e for e in result.edges if e.kind.value == "imports"]
    assert len(import_edges) == 2
    assert import_edges[0].id != import_edges[1].id  # never collide despite identical id inputs
    assert all(e.raw_target_expression == ".utils" for e in import_edges)
    assert all(e.resolution_status is ResolutionStatus.RESOLVED for e in import_edges)


async def test_two_identical_calls_at_an_identical_location_get_distinct_edge_ids() -> None:
    # Same collision-protection guarantee as the imports case above, for
    # CALLS edges — the same caller symbol issuing the exact same call twice
    # (e.g. `helper(); helper()`) at an identical SourceLocation must not
    # collapse into one persisted edge.
    service, repositories, parsed_files, _ = _service()
    repository = await _seed_ready_repository(repositories)

    helper = Symbol(
        id=uuid4(),
        kind=SymbolKind.FUNCTION,
        name="helper",
        qualified_name="helper",
        location=_LOCATION,
        parameters=(),
        parent_symbol_id=None,
    )
    caller = Symbol(
        id=uuid4(),
        kind=SymbolKind.FUNCTION,
        name="main",
        qualified_name="main",
        location=_LOCATION,
        parameters=(),
        parent_symbol_id=None,
        calls=(
            CallReference(callee_expression="helper", location=_LOCATION),
            CallReference(callee_expression="helper", location=_LOCATION),
        ),
    )
    file = _python_file("main.py", symbols=(caller, helper))
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id, files=(file,), errors=(), parsed_at=datetime.now(UTC)
        )
    )

    result = await service.analyze_repository(repository.id)

    call_edges = [e for e in result.edges if e.kind.value == "calls"]
    assert len(call_edges) == 2
    assert call_edges[0].id != call_edges[1].id  # never collide despite identical id inputs
    assert all(e.raw_target_expression == "helper" for e in call_edges)
    assert all(e.resolution_status is ResolutionStatus.RESOLVED for e in call_edges)


async def test_resolves_a_function_call_between_two_files() -> None:
    service, repositories, parsed_files, _ = _service()
    repository = await _seed_ready_repository(repositories)

    target = Symbol(
        id=uuid4(),
        kind=SymbolKind.FUNCTION,
        name="helper",
        qualified_name="helper",
        location=_LOCATION,
        parameters=(),
        parent_symbol_id=None,
    )
    utils_file = _python_file("utils.py", symbols=(target,))
    caller = Symbol(
        id=uuid4(),
        kind=SymbolKind.FUNCTION,
        name="main",
        qualified_name="main",
        location=_LOCATION,
        parameters=(),
        parent_symbol_id=None,
        calls=(CallReference(callee_expression="helper", location=_LOCATION),),
    )
    main_file = _python_file(
        "main.py",
        imports=(
            Import(
                id=uuid4(),
                module=".utils",
                imported_names=("helper",),
                alias=None,
                location=_LOCATION,
            ),
        ),
        symbols=(caller,),
    )
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(main_file, utils_file),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )

    result = await service.analyze_repository(repository.id)

    calls_edges = [e for e in result.edges if e.kind.value == "calls"]
    assert len(calls_edges) == 1
    assert calls_edges[0].resolution_status is ResolutionStatus.RESOLVED
    assert calls_edges[0].source_symbol_id == caller.id
    assert calls_edges[0].target_symbol_id == target.id


async def test_resolves_inheritance_between_two_files() -> None:
    service, repositories, parsed_files, _ = _service()
    repository = await _seed_ready_repository(repositories)

    base = Symbol(
        id=uuid4(),
        kind=SymbolKind.CLASS,
        name="Base",
        qualified_name="Base",
        location=_LOCATION,
        parameters=(),
        parent_symbol_id=None,
    )
    base_file = _python_file("base.py", symbols=(base,))
    sub = Symbol(
        id=uuid4(),
        kind=SymbolKind.CLASS,
        name="Sub",
        qualified_name="Sub",
        location=_LOCATION,
        parameters=(),
        parent_symbol_id=None,
        base_class_names=("Base",),
    )
    sub_file = _python_file(
        "sub.py",
        imports=(
            Import(
                id=uuid4(),
                module=".base",
                imported_names=("Base",),
                alias=None,
                location=_LOCATION,
            ),
        ),
        symbols=(sub,),
    )
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(sub_file, base_file),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )

    result = await service.analyze_repository(repository.id)

    inherits_edges = [e for e in result.edges if e.kind.value == "inherits"]
    assert len(inherits_edges) == 1
    assert inherits_edges[0].resolution_status is ResolutionStatus.RESOLVED
    assert inherits_edges[0].source_symbol_id == sub.id
    assert inherits_edges[0].target_symbol_id == base.id


async def test_unresolved_call_does_not_abort_analysis_of_other_edges() -> None:
    service, repositories, parsed_files, _ = _service()
    repository = await _seed_ready_repository(repositories)

    caller = Symbol(
        id=uuid4(),
        kind=SymbolKind.FUNCTION,
        name="main",
        qualified_name="main",
        location=_LOCATION,
        parameters=(),
        parent_symbol_id=None,
        calls=(CallReference(callee_expression="mystery", location=_LOCATION),),
    )
    main_file = _python_file(
        "main.py",
        imports=(
            Import(
                id=uuid4(), module="external", imported_names=(), alias=None, location=_LOCATION
            ),
        ),
        symbols=(caller,),
    )
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id, files=(main_file,), errors=(), parsed_at=datetime.now(UTC)
        )
    )

    result = await service.analyze_repository(repository.id)

    assert len(result.edges) == 2  # the import edge AND the call edge, both present
    assert all(e.resolution_status is ResolutionStatus.UNRESOLVED for e in result.edges)
