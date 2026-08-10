"""Orchestration tests for `GraphService`.

Exercises the full workflow — repository lookup, loading parsed files/edges,
mapping, projecting — against in-memory fakes for every port (see
tests/fakes.py), mirroring test_dependency_analysis_service.py's established
"real everything except the backend" approach.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from forge.application.graph.service import GraphService
from forge.domain.errors import (
    GraphUnavailableError,
    NotFoundError,
    UnsupportedRepositoryStateError,
)
from forge.domain.graph.entities import GraphNodeKind
from forge.domain.parsing.entities import Language, ParsedFile, ParseResult, SourceLocation
from forge.domain.repository.entities import Repository, RepositorySourceType, RepositoryStatus
from tests.fakes import (
    InMemoryDependencyEdgeRepository,
    InMemoryGraphRepository,
    InMemoryParsedFileRepository,
    InMemoryRepositoryRepository,
)

_LOCATION = SourceLocation(start_line=1, end_line=1, start_column=0, end_column=None)


def _service() -> tuple[
    GraphService,
    InMemoryRepositoryRepository,
    InMemoryParsedFileRepository,
    InMemoryDependencyEdgeRepository,
    InMemoryGraphRepository,
]:
    repositories = InMemoryRepositoryRepository()
    parsed_files = InMemoryParsedFileRepository()
    dependency_edges = InMemoryDependencyEdgeRepository()
    graph = InMemoryGraphRepository()
    service = GraphService(
        repositories=repositories,
        parsed_files=parsed_files,
        dependency_edges=dependency_edges,
        graph=graph,
    )
    return service, repositories, parsed_files, dependency_edges, graph


async def _seed_ready_repository(
    repositories: InMemoryRepositoryRepository, *, status: RepositoryStatus = RepositoryStatus.READY
) -> Repository:
    now = datetime.now(UTC)
    repository = Repository(
        id=uuid4(),
        project_id=uuid4(),
        source_type=RepositorySourceType.ZIP,
        source_ref="upload.zip",
        display_name="Demo",
        workspace_path="/tmp/does-not-matter",
        status=status,
        metadata=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    await repositories.create(repository)
    return repository


def _file(repository_id, path: str) -> ParsedFile:
    return ParsedFile(
        id=uuid4(),
        repository_id=repository_id,
        path=path,
        language=Language.PYTHON,
        symbols=(),
        imports=(),
        has_syntax_errors=False,
    )


async def test_projects_a_ready_and_parsed_repository() -> None:
    service, repositories, parsed_files, _, graph = _service()
    repository = await _seed_ready_repository(repositories)
    file = _file(repository.id, "main.py")
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id, files=(file,), errors=(), parsed_at=datetime.now(UTC)
        )
    )

    result = await service.project_repository(repository.id)

    assert result.repository_id == repository.id
    assert result.node_count == 2  # repository + file
    persisted_nodes = await graph.get_nodes(repository.id)
    assert len(persisted_nodes) == 2


async def test_projecting_unknown_repository_raises_not_found() -> None:
    service, _, _, _, _ = _service()
    with pytest.raises(NotFoundError):
        await service.project_repository(uuid4())


async def test_projecting_non_ready_repository_is_rejected() -> None:
    service, repositories, _, _, _ = _service()
    repository = await _seed_ready_repository(repositories, status=RepositoryStatus.IMPORTING)
    with pytest.raises(UnsupportedRepositoryStateError):
        await service.project_repository(repository.id)


async def test_projecting_unparsed_repository_is_rejected() -> None:
    service, repositories, _, _, _ = _service()
    repository = await _seed_ready_repository(repositories)  # READY, but never parsed
    with pytest.raises(UnsupportedRepositoryStateError):
        await service.project_repository(repository.id)


async def test_projecting_with_neo4j_unavailable_raises_graph_unavailable() -> None:
    service, repositories, parsed_files, _, graph = _service()
    repository = await _seed_ready_repository(repositories)
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(_file(repository.id, "main.py"),),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )
    graph.available = False

    with pytest.raises(GraphUnavailableError):
        await service.project_repository(repository.id)


async def test_projecting_with_no_dependencies_still_projects_structural_nodes() -> None:
    service, repositories, parsed_files, dependency_edges, graph = _service()
    repository = await _seed_ready_repository(repositories)
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(_file(repository.id, "main.py"),),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )
    # dependency_edges deliberately left empty — parsed but never analyzed.

    result = await service.project_repository(repository.id)

    assert result.relationship_count == 1  # just the CONTAINS edge
    assert result.node_count == 2


async def test_reprojection_replaces_previous_graph() -> None:
    service, repositories, parsed_files, _, graph = _service()
    repository = await _seed_ready_repository(repositories)
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(_file(repository.id, "main.py"),),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )

    await service.project_repository(repository.id)
    await service.project_repository(repository.id)

    nodes = await graph.get_nodes(repository.id)
    assert len(nodes) == 2  # not duplicated


async def test_get_nodes_requires_repository_to_exist() -> None:
    service, _, _, _, _ = _service()
    with pytest.raises(NotFoundError):
        await service.get_nodes(uuid4())


async def test_get_nodes_returns_empty_list_before_any_projection() -> None:
    service, repositories, _, _, _ = _service()
    repository = await _seed_ready_repository(repositories)

    nodes = await service.get_nodes(repository.id)

    assert nodes == []


async def test_get_neighbors_raises_not_found_for_unknown_node() -> None:
    service, repositories, parsed_files, _, _ = _service()
    repository = await _seed_ready_repository(repositories)
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(_file(repository.id, "main.py"),),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )
    await service.project_repository(repository.id)

    with pytest.raises(NotFoundError):
        await service.get_neighbors(repository.id, uuid4())


async def test_get_neighbors_returns_connected_nodes() -> None:
    service, repositories, parsed_files, _, _ = _service()
    repository = await _seed_ready_repository(repositories)
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(_file(repository.id, "main.py"),),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )
    await service.project_repository(repository.id)

    neighbors = await service.get_neighbors(repository.id, repository.id)

    assert len(neighbors) == 1
    assert neighbors[0].node.kind is GraphNodeKind.FILE


async def test_failed_projection_does_not_corrupt_later_calls() -> None:
    service, repositories, parsed_files, _, graph = _service()
    repository = await _seed_ready_repository(repositories)
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=(_file(repository.id, "main.py"),),
            errors=(),
            parsed_at=datetime.now(UTC),
        )
    )
    graph.available = False
    with pytest.raises(GraphUnavailableError):
        await service.project_repository(repository.id)

    graph.available = True
    result = await service.project_repository(repository.id)

    assert result.node_count == 2
