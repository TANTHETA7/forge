"""Orchestration tests for `GraphIntelligenceService` — dependency/dependent
exploration slice (Capability 1). Mirrors test_graph_service.py's
established "real everything except the backend" approach: real service
logic against in-memory fakes for both `RepositoryRepository` and
`GraphRepository`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from forge.application.graph_intelligence.service import GraphIntelligenceService
from forge.domain.dependency_analysis.entities import (
    DependencyEdge,
    DependencyKind,
    ResolutionStatus,
)
from forge.domain.errors import NotFoundError
from forge.domain.graph.entities import (
    GraphNode,
    GraphNodeKind,
    GraphRelationship,
    GraphRelationshipKind,
)
from forge.domain.graph_intelligence.entities import DependencyDirection
from forge.domain.parsing.entities import ParseResult, SourceLocation
from forge.domain.repository.entities import Repository, RepositorySourceType, RepositoryStatus
from tests.fakes import (
    InMemoryDependencyEdgeRepository,
    InMemoryGraphIntelligenceRepository,
    InMemoryGraphRepository,
    InMemoryParsedFileRepository,
    InMemoryRepositoryRepository,
)


def _service() -> (
    tuple[GraphIntelligenceService, InMemoryRepositoryRepository, InMemoryGraphRepository]
):
    service, repositories, graph, _parsed_files, _dependency_edges = _service_full()
    return service, repositories, graph


def _service_with_parsed_files() -> tuple[
    GraphIntelligenceService,
    InMemoryRepositoryRepository,
    InMemoryGraphRepository,
    InMemoryParsedFileRepository,
]:
    service, repositories, graph, parsed_files, _dependency_edges = _service_full()
    return service, repositories, graph, parsed_files


def _service_full() -> tuple[
    GraphIntelligenceService,
    InMemoryRepositoryRepository,
    InMemoryGraphRepository,
    InMemoryParsedFileRepository,
    InMemoryDependencyEdgeRepository,
]:
    repositories = InMemoryRepositoryRepository()
    graph = InMemoryGraphRepository()
    intelligence = InMemoryGraphIntelligenceRepository(graph)
    parsed_files = InMemoryParsedFileRepository()
    dependency_edges = InMemoryDependencyEdgeRepository()
    service = GraphIntelligenceService(
        repositories=repositories,
        graph=graph,
        intelligence=intelligence,
        parsed_files=parsed_files,
        dependency_edges=dependency_edges,
    )
    return service, repositories, graph, parsed_files, dependency_edges


async def _seed_repository(repositories: InMemoryRepositoryRepository) -> Repository:
    now = datetime.now(UTC)
    repository = Repository(
        id=uuid4(),
        project_id=uuid4(),
        source_type=RepositorySourceType.ZIP,
        source_ref="upload.zip",
        display_name="Demo",
        workspace_path="/tmp/does-not-matter",
        status=RepositoryStatus.READY,
        metadata=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    await repositories.create(repository)
    return repository


def _node(repository_id, kind=GraphNodeKind.SYMBOL) -> GraphNode:
    return GraphNode(id=uuid4(), kind=kind, repository_id=repository_id, properties={})


async def _seed_chain(graph: InMemoryGraphRepository, repository_id):
    """A -[CALLS]-> B -[CALLS]-> C, plus B -[IMPORTS]-> D, for kind filtering."""
    a, b, c, d = (_node(repository_id) for _ in range(4))
    rel_ab = GraphRelationship(
        source_id=a.id, target_id=b.id, kind=GraphRelationshipKind.CALLS,
        repository_id=repository_id, dependency_edge_id=None, properties={},
    )
    rel_bc = GraphRelationship(
        source_id=b.id, target_id=c.id, kind=GraphRelationshipKind.CALLS,
        repository_id=repository_id, dependency_edge_id=None, properties={},
    )
    rel_bd = GraphRelationship(
        source_id=b.id, target_id=d.id, kind=GraphRelationshipKind.IMPORTS,
        repository_id=repository_id, dependency_edge_id=None, properties={},
    )
    await graph.project_repository(repository_id, (a, b, c, d), (rel_ab, rel_bc, rel_bd))
    return a, b, c, d


async def test_get_dependencies_is_the_downstream_direction() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_chain(graph, repository.id)

    dependencies = await service.get_dependencies(repository.id, b.id)

    assert {n.node.id for n in dependencies} == {c.id, d.id}  # B depends on C and D


async def test_get_dependents_is_the_upstream_direction() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_chain(graph, repository.id)

    dependents = await service.get_dependents(repository.id, b.id)

    assert {n.node.id for n in dependents} == {a.id}  # only A depends on B


async def test_get_dependencies_filters_by_relationship_kind() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_chain(graph, repository.id)

    calls_only = await service.get_dependencies(
        repository.id, b.id, kind=GraphRelationshipKind.CALLS
    )
    imports_only = await service.get_dependencies(
        repository.id, b.id, kind=GraphRelationshipKind.IMPORTS
    )

    assert {n.node.id for n in calls_only} == {c.id}
    assert {n.node.id for n in imports_only} == {d.id}


async def test_get_dependencies_of_a_leaf_node_is_empty() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_chain(graph, repository.id)

    dependencies = await service.get_dependencies(repository.id, c.id)  # C depends on nothing

    assert dependencies == []


async def test_get_dependencies_unknown_node_raises_not_found() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    await graph.project_repository(repository.id, (), ())

    with pytest.raises(NotFoundError):
        await service.get_dependencies(repository.id, uuid4())


async def test_get_dependents_unknown_node_raises_not_found() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    await graph.project_repository(repository.id, (), ())

    with pytest.raises(NotFoundError):
        await service.get_dependents(repository.id, uuid4())


async def test_get_dependencies_unknown_repository_raises_not_found() -> None:
    service, _repositories, _graph = _service()
    with pytest.raises(NotFoundError):
        await service.get_dependencies(uuid4(), uuid4())


async def test_get_dependencies_respects_limit() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    hub = _node(repository.id)
    leaves = [_node(repository.id) for _ in range(5)]
    rels = [
        GraphRelationship(
            source_id=hub.id, target_id=leaf.id, kind=GraphRelationshipKind.CALLS,
            repository_id=repository.id, dependency_edge_id=None, properties={},
        )
        for leaf in leaves
    ]
    await graph.project_repository(repository.id, (hub, *leaves), tuple(rels))

    dependencies = await service.get_dependencies(repository.id, hub.id, limit=2)

    assert len(dependencies) == 2


async def test_node_with_no_incoming_edges_has_no_dependents() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_chain(graph, repository.id)

    dependents = await service.get_dependents(repository.id, a.id)  # nothing calls A

    assert dependents == []


async def _seed_linear_chain(graph: InMemoryGraphRepository, repository_id):
    """A -[CALLS]-> B -[CALLS]-> C -[CALLS]-> D — a plain 4-node chain, the
    exact shape of the brief's Capability 2/3 examples (distinct from
    `_seed_chain`, which branches at B for kind-filtering tests)."""
    a, b, c, d = (_node(repository_id) for _ in range(4))
    rels = (
        GraphRelationship(
            source_id=a.id, target_id=b.id, kind=GraphRelationshipKind.CALLS,
            repository_id=repository_id, dependency_edge_id=None, properties={},
        ),
        GraphRelationship(
            source_id=b.id, target_id=c.id, kind=GraphRelationshipKind.CALLS,
            repository_id=repository_id, dependency_edge_id=None, properties={},
        ),
        GraphRelationship(
            source_id=c.id, target_id=d.id, kind=GraphRelationshipKind.CALLS,
            repository_id=repository_id, dependency_edge_id=None, properties={},
        ),
    )
    await graph.project_repository(repository_id, (a, b, c, d), rels)
    return a, b, c, d


async def test_impact_defaults_to_upstream_direction() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_linear_chain(graph, repository.id)

    result = await service.get_impact(repository.id, c.id, max_depth=2, limit=100)

    assert result.direction is DependencyDirection.UPSTREAM
    assert {n.node.id for n in result.impacted_nodes} == {a.id, b.id}


async def test_impact_downstream_matches_brief_example() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_linear_chain(graph, repository.id)

    depth_1 = await service.get_impact(
        repository.id, b.id, direction=DependencyDirection.DOWNSTREAM, max_depth=1, limit=100
    )
    depth_2 = await service.get_impact(
        repository.id, b.id, direction=DependencyDirection.DOWNSTREAM, max_depth=2, limit=100
    )

    assert {n.node.id for n in depth_1.impacted_nodes} == {c.id}
    assert {n.node.id for n in depth_2.impacted_nodes} == {c.id, d.id}


async def test_impact_never_includes_the_starting_node() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a = _node(repository.id)
    b = _node(repository.id)
    rel_ab = GraphRelationship(
        source_id=a.id, target_id=b.id, kind=GraphRelationshipKind.CALLS,
        repository_id=repository.id, dependency_edge_id=None, properties={},
    )
    rel_ba = GraphRelationship(
        source_id=b.id, target_id=a.id, kind=GraphRelationshipKind.CALLS,
        repository_id=repository.id, dependency_edge_id=None, properties={},
    )
    await graph.project_repository(repository.id, (a, b), (rel_ab, rel_ba))

    result = await service.get_impact(
        repository.id, a.id, direction=DependencyDirection.DOWNSTREAM, max_depth=5, limit=100
    )

    assert a.id not in {n.node.id for n in result.impacted_nodes}


async def test_impact_unknown_node_raises_not_found() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    await graph.project_repository(repository.id, (), ())

    with pytest.raises(NotFoundError):
        await service.get_impact(repository.id, uuid4(), max_depth=3, limit=100)


async def test_impact_unknown_repository_raises_not_found() -> None:
    service, _repositories, _graph = _service()
    with pytest.raises(NotFoundError):
        await service.get_impact(uuid4(), uuid4(), max_depth=3, limit=100)


async def test_impact_of_a_node_with_nothing_upstream_is_empty() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_linear_chain(graph, repository.id)

    # nothing calls A
    result = await service.get_impact(repository.id, a.id, max_depth=3, limit=100)

    assert result.impacted_nodes == ()


async def test_path_finds_the_directed_route() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_linear_chain(graph, repository.id)

    result = await service.get_path(repository.id, a.id, d.id, max_depth=6)

    assert result.found is True
    assert [n.id for n in result.nodes] == [a.id, b.id, c.id, d.id]
    assert result.length == 3


async def test_path_not_found_is_a_normal_result_not_an_exception() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_linear_chain(graph, repository.id)

    result = await service.get_path(repository.id, d.id, a.id, max_depth=6)  # reverse direction

    assert result.found is False
    assert result.nodes == ()
    assert result.length is None


async def test_path_same_node_is_well_defined() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_linear_chain(graph, repository.id)

    result = await service.get_path(repository.id, b.id, b.id, max_depth=6)

    assert result.found is True
    assert [n.id for n in result.nodes] == [b.id]
    assert result.length == 0


async def test_path_unknown_source_raises_not_found() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_linear_chain(graph, repository.id)

    with pytest.raises(NotFoundError):
        await service.get_path(repository.id, uuid4(), d.id, max_depth=6)


async def test_path_unknown_target_raises_not_found() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_linear_chain(graph, repository.id)

    with pytest.raises(NotFoundError):
        await service.get_path(repository.id, a.id, uuid4(), max_depth=6)


async def test_path_unknown_repository_raises_not_found() -> None:
    service, _repositories, _graph = _service()
    with pytest.raises(NotFoundError):
        await service.get_path(uuid4(), uuid4(), uuid4(), max_depth=6)


async def test_path_respects_max_depth_bound() -> None:
    service, repositories, graph = _service()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_linear_chain(graph, repository.id)  # length 3

    too_short = await service.get_path(repository.id, a.id, d.id, max_depth=2)

    assert too_short.found is False


async def test_statistics_counts_nodes_and_relationships() -> None:
    service, repositories, graph, _parsed_files = _service_with_parsed_files()
    repository = await _seed_repository(repositories)
    a, b, c, d = await _seed_linear_chain(graph, repository.id)

    stats = await service.get_statistics(repository.id)

    assert stats.total_nodes == 4
    assert stats.total_symbols == 4
    assert stats.total_files == 0
    assert stats.total_relationships == 3
    calls_count = next(
        entry.count
        for entry in stats.relationships_by_kind
        if entry.kind is GraphRelationshipKind.CALLS
    )
    assert calls_count == 3
    imports_count = next(
        entry.count
        for entry in stats.relationships_by_kind
        if entry.kind is GraphRelationshipKind.IMPORTS
    )
    assert imports_count == 0  # every kind present, zero-filled


async def test_statistics_highest_degree_rankings() -> None:
    service, repositories, graph, _parsed_files = _service_with_parsed_files()
    repository = await _seed_repository(repositories)
    hub = _node(repository.id)
    leaves = [_node(repository.id) for _ in range(3)]
    rels = [
        GraphRelationship(
            source_id=hub.id, target_id=leaf.id, kind=GraphRelationshipKind.CALLS,
            repository_id=repository.id, dependency_edge_id=None, properties={},
        )
        for leaf in leaves
    ]
    await graph.project_repository(repository.id, (hub, *leaves), tuple(rels))

    stats = await service.get_statistics(repository.id)

    assert stats.highest_out_degree[0].node.id == hub.id
    assert stats.highest_out_degree[0].degree == 3
    assert sorted(entry.degree for entry in stats.highest_in_degree) == [1, 1, 1]


async def test_statistics_unprojected_repository_is_all_zero_not_error() -> None:
    service, repositories, graph, _parsed_files = _service_with_parsed_files()
    repository = await _seed_repository(repositories)

    stats = await service.get_statistics(repository.id)

    assert stats.total_nodes == 0
    assert stats.freshness == "not_projected"
    assert stats.projected_at is None


async def test_statistics_unknown_repository_raises_not_found() -> None:
    service, _repositories, _graph, _parsed_files = _service_with_parsed_files()
    with pytest.raises(NotFoundError):
        await service.get_statistics(uuid4())


async def test_statistics_freshness_is_fresh_when_never_reparsed_since_projection() -> None:
    service, repositories, graph, parsed_files = _service_with_parsed_files()
    repository = await _seed_repository(repositories)
    # A `:Repository`-kind node is required for `projected_at` to be stamped
    # (see infrastructure/graph/neo4j_graph_repository.py::_write_projected_at_tx
    # and its InMemoryGraphRepository mirror) — `_seed_linear_chain` only
    # builds SYMBOL nodes, so it's insufficient for freshness tests alone.
    repository_node = GraphNode(
        id=repository.id, kind=GraphNodeKind.REPOSITORY, repository_id=repository.id, properties={}
    )
    # Parsed strictly BEFORE projection (not merely "not after" — two
    # back-to-back `datetime.now()` calls could otherwise coincidentally
    # land in either order at microsecond granularity), matching the normal
    # parse-then-project sequence.
    earlier = datetime.now(UTC) - timedelta(seconds=1)
    await parsed_files.save_parse_result(
        ParseResult(repository_id=repository.id, files=(), errors=(), parsed_at=earlier)
    )
    await graph.project_repository(repository.id, (repository_node,), ())

    stats = await service.get_statistics(repository.id)

    assert stats.freshness == "fresh"


async def test_statistics_freshness_is_stale_after_a_later_reparse() -> None:
    service, repositories, graph, parsed_files = _service_with_parsed_files()
    repository = await _seed_repository(repositories)
    repository_node = GraphNode(
        id=repository.id, kind=GraphNodeKind.REPOSITORY, repository_id=repository.id, properties={}
    )
    await graph.project_repository(repository.id, (repository_node,), ())  # projects "now"

    # Simulate a re-parse that happened AFTER projection.
    later = datetime.now(UTC) + timedelta(hours=1)
    await parsed_files.save_parse_result(
        ParseResult(repository_id=repository.id, files=(), errors=(), parsed_at=later)
    )

    stats = await service.get_statistics(repository.id)

    assert stats.freshness == "stale"


def _import_edge(repository_id, source_file_id, status) -> DependencyEdge:
    return DependencyEdge(
        id=uuid4(),
        repository_id=repository_id,
        kind=DependencyKind.IMPORTS,
        resolution_status=status,
        source_file_id=source_file_id,
        source_symbol_id=None,
        target_file_id=None,
        target_symbol_id=None,
        raw_target_expression="external_thing",
        location=SourceLocation(1, 1, 0, None),
        detail=None,
    )


async def test_insights_isolated_nodes_and_hotspots() -> None:
    service, repositories, graph, _parsed_files, _dependency_edges = _service_full()
    repository = await _seed_repository(repositories)
    hub = _node(repository.id)
    isolated = _node(repository.id)
    other = _node(repository.id)
    rel = GraphRelationship(
        source_id=hub.id, target_id=other.id, kind=GraphRelationshipKind.CALLS,
        repository_id=repository.id, dependency_edge_id=None, properties={},
    )
    await graph.project_repository(repository.id, (hub, isolated, other), (rel,))

    insights = await service.get_insights(repository.id)

    assert insights.dependency_hotspots[0].node.id in {hub.id, other.id}
    isolated_ids = {n.id for n in insights.isolated_nodes}
    assert isolated.id in isolated_ids
    assert hub.id not in isolated_ids


async def test_insights_unresolved_count_reads_from_dependency_edges() -> None:
    service, repositories, graph, _parsed_files, dependency_edges = _service_full()
    repository = await _seed_repository(repositories)
    await graph.project_repository(repository.id, (), ())
    file_id = uuid4()
    await dependency_edges.save_analysis_result(
        repository.id,
        (
            _import_edge(repository.id, file_id, ResolutionStatus.UNRESOLVED),
            _import_edge(repository.id, file_id, ResolutionStatus.UNRESOLVED),
            _import_edge(repository.id, file_id, ResolutionStatus.RESOLVED),
        ),
    )

    insights = await service.get_insights(repository.id)

    assert insights.unresolved_dependency_count == 2  # RESOLVED edge not counted


async def test_insights_unknown_repository_raises_not_found() -> None:
    service, _repositories, _graph, _parsed_files, _dependency_edges = _service_full()
    with pytest.raises(NotFoundError):
        await service.get_insights(uuid4())


async def test_insights_of_an_unprojected_repository_is_all_empty() -> None:
    service, repositories, graph, _parsed_files, _dependency_edges = _service_full()
    repository = await _seed_repository(repositories)
    await graph.project_repository(repository.id, (), ())

    insights = await service.get_insights(repository.id)

    assert insights.most_connected_files == ()
    assert insights.dependency_hotspots == ()
    assert insights.isolated_nodes == ()
    assert insights.mutual_import_pairs == ()
    assert insights.unresolved_dependency_count == 0
