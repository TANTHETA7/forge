"""End-to-end test of `Neo4jGraphIntelligenceRepository` against a REAL
Neo4j instance — not a fake, mirroring test_neo4j_graph_projection.py's own
rationale: traversal/aggregation correctness only surfaces against the real
backend. Graphs are hand-built directly via `Neo4jGraphRepository.
project_repository` (same pattern as test_neo4j_graph_projection.py), not
through the full import/parse/analyze pipeline — that full-pipeline
correctness is covered separately by test_real_graph_intelligence.py.

Uses the shared `neo4j_graph` fixture from tests/integration/conftest.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from neo4j import AsyncGraphDatabase, AsyncSession

from forge.domain.errors import GraphUnavailableError
from forge.domain.graph.entities import (
    GraphNode,
    GraphNodeKind,
    GraphRelationship,
    GraphRelationshipKind,
)
from forge.domain.graph_intelligence.entities import DependencyDirection
from forge.infrastructure.graph.neo4j_graph_repository import Neo4jGraphRepository
from forge.infrastructure.graph_intelligence.neo4j_graph_intelligence_repository import (
    Neo4jGraphIntelligenceRepository,
)
from tests.integration.conftest import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER


@pytest_asyncio.fixture
async def session(neo4j_graph: None) -> AsyncIterator[AsyncSession]:
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    async with driver.session() as session_:
        yield session_
    await driver.close()


def _symbol(repository_id: UUID) -> GraphNode:
    return GraphNode(
        id=uuid4(), kind=GraphNodeKind.SYMBOL, repository_id=repository_id, properties={}
    )


def _repository_node(repository_id: UUID) -> GraphNode:
    return GraphNode(
        id=repository_id, kind=GraphNodeKind.REPOSITORY, repository_id=repository_id, properties={}
    )


def _file(repository_id: UUID, path: str) -> GraphNode:
    return GraphNode(
        id=uuid4(),
        kind=GraphNodeKind.FILE,
        repository_id=repository_id,
        properties={"path": path},
    )


def _rel(
    repository_id: UUID, source_id: UUID, target_id: UUID, kind: GraphRelationshipKind
) -> GraphRelationship:
    return GraphRelationship(
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        repository_id=repository_id,
        dependency_edge_id=uuid4(),
        properties={},
    )


async def _seed_chain(session: AsyncSession, repository_id: UUID) -> tuple[GraphNode, ...]:
    """A -[CALLS]-> B -[CALLS]-> C -[CALLS]-> D, a linear 4-node chain."""
    projector = Neo4jGraphRepository(session)
    a, b, c, d = (_symbol(repository_id) for _ in range(4))
    rels = (
        _rel(repository_id, a.id, b.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, b.id, c.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, c.id, d.id, GraphRelationshipKind.CALLS),
    )
    await projector.project_repository(repository_id, (a, b, c, d), rels)
    return a, b, c, d


async def test_downstream_impact_matches_brief_example(session: AsyncSession) -> None:
    """A -> B -> C -> D. If B changes, DOWNSTREAM impact at depth 1 is {C},
    depth 2 is {C, D} — the brief's own literal Capability 3 example,
    verified as an available (non-default) traversal direction."""
    repository_id = uuid4()
    a, b, c, d = await _seed_chain(session, repository_id)
    repo = Neo4jGraphIntelligenceRepository(session)

    depth_1 = await repo.get_impact(
        repository_id, b.id, direction=DependencyDirection.DOWNSTREAM, max_depth=1, limit=100
    )
    depth_2 = await repo.get_impact(
        repository_id, b.id, direction=DependencyDirection.DOWNSTREAM, max_depth=2, limit=100
    )

    assert depth_1 is not None
    assert {n.node.id for n in depth_1.impacted_nodes} == {c.id}
    assert depth_2 is not None
    assert {n.node.id for n in depth_2.impacted_nodes} == {c.id, d.id}


async def test_upstream_impact_is_the_default_and_correct_direction(session: AsyncSession) -> None:
    """A -> B -> C -> D. If C changes, UPSTREAM impact (the confirmed
    default — "what could be affected") is everything that transitively
    depends on C: at depth 1, {B}; at depth 2, {A, B}."""
    repository_id = uuid4()
    a, b, c, d = await _seed_chain(session, repository_id)
    repo = Neo4jGraphIntelligenceRepository(session)

    depth_1 = await repo.get_impact(repository_id, c.id, max_depth=1, limit=100)
    depth_2 = await repo.get_impact(repository_id, c.id, max_depth=2, limit=100)

    assert depth_1 is not None
    assert depth_1.direction is DependencyDirection.UPSTREAM  # confirmed default
    assert {n.node.id for n in depth_1.impacted_nodes} == {b.id}
    assert depth_2 is not None
    assert {n.node.id for n in depth_2.impacted_nodes} == {a.id, b.id}


async def test_impact_reports_shortest_depth_with_multiple_paths(session: AsyncSession) -> None:
    """A -[CALLS]-> B -[CALLS]-> D, and A -[CALLS]-> C -[CALLS]-> D -- D is
    reachable from A at depth 2 via two different paths; must appear exactly
    once, at depth 2, not duplicated."""
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    a, b, c, d = (_symbol(repository_id) for _ in range(4))
    rels = (
        _rel(repository_id, a.id, b.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, a.id, c.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, b.id, d.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, c.id, d.id, GraphRelationshipKind.CALLS),
    )
    await projector.project_repository(repository_id, (a, b, c, d), rels)
    repo = Neo4jGraphIntelligenceRepository(session)

    result = await repo.get_impact(
        repository_id, a.id, direction=DependencyDirection.DOWNSTREAM, max_depth=5, limit=100
    )

    assert result is not None
    by_id = {n.node.id: n for n in result.impacted_nodes}
    assert set(by_id) == {b.id, c.id, d.id}
    assert by_id[d.id].depth == 2  # shortest, not duplicated at depth 2 twice


async def test_impact_excludes_the_starting_node_even_with_a_cycle(session: AsyncSession) -> None:
    """A -[CALLS]-> B -[CALLS]-> A (a direct cycle). Impact of A must never
    include A itself."""
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    a, b = (_symbol(repository_id) for _ in range(2))
    rels = (
        _rel(repository_id, a.id, b.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, b.id, a.id, GraphRelationshipKind.CALLS),
    )
    await projector.project_repository(repository_id, (a, b), rels)
    repo = Neo4jGraphIntelligenceRepository(session)

    result = await repo.get_impact(
        repository_id, a.id, direction=DependencyDirection.DOWNSTREAM, max_depth=5, limit=100
    )

    assert result is not None
    assert a.id not in {n.node.id for n in result.impacted_nodes}
    assert {n.node.id for n in result.impacted_nodes} == {b.id}


async def test_impact_respects_relationship_kind_filter(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    a, b, c = (_symbol(repository_id) for _ in range(3))
    rels = (
        _rel(repository_id, a.id, b.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, a.id, c.id, GraphRelationshipKind.IMPORTS),
    )
    await projector.project_repository(repository_id, (a, b, c), rels)
    repo = Neo4jGraphIntelligenceRepository(session)

    calls_only = await repo.get_impact(
        repository_id,
        a.id,
        direction=DependencyDirection.DOWNSTREAM,
        max_depth=3,
        kind=GraphRelationshipKind.CALLS,
        limit=100,
    )

    assert calls_only is not None
    assert {n.node.id for n in calls_only.impacted_nodes} == {b.id}


async def test_impact_respects_limit(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    hub = _symbol(repository_id)
    leaves = [_symbol(repository_id) for _ in range(5)]
    rels = tuple(
        _rel(repository_id, hub.id, leaf.id, GraphRelationshipKind.CALLS) for leaf in leaves
    )
    await projector.project_repository(repository_id, (hub, *leaves), rels)
    repo = Neo4jGraphIntelligenceRepository(session)

    result = await repo.get_impact(
        repository_id, hub.id, direction=DependencyDirection.DOWNSTREAM, max_depth=3, limit=2
    )

    assert result is not None
    assert len(result.impacted_nodes) == 2


async def test_impact_returns_none_for_unknown_node(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    node = _symbol(repository_id)
    await projector.project_repository(repository_id, (node,), ())
    repo = Neo4jGraphIntelligenceRepository(session)

    assert await repo.get_impact(repository_id, uuid4(), max_depth=3, limit=100) is None


async def test_impact_returns_none_for_cross_repository_node(session: AsyncSession) -> None:
    repository_a = uuid4()
    repository_b = uuid4()
    projector = Neo4jGraphRepository(session)
    node_in_a = _symbol(repository_a)
    await projector.project_repository(repository_a, (node_in_a,), ())
    await projector.project_repository(repository_b, (_symbol(repository_b),), ())
    repo = Neo4jGraphIntelligenceRepository(session)

    assert await repo.get_impact(repository_b, node_in_a.id, max_depth=3, limit=100) is None


async def test_impact_of_a_leaf_node_is_empty(session: AsyncSession) -> None:
    repository_id = uuid4()
    a, b, c, d = await _seed_chain(session, repository_id)
    repo = Neo4jGraphIntelligenceRepository(session)

    result = await repo.get_impact(
        repository_id, d.id, direction=DependencyDirection.DOWNSTREAM, max_depth=3, limit=100
    )

    assert result is not None
    assert result.impacted_nodes == ()


async def test_two_repositories_never_cross_contaminate_impact(session: AsyncSession) -> None:
    repository_a = uuid4()
    repository_b = uuid4()
    await _seed_chain(session, repository_a)
    b_nodes = await _seed_chain(session, repository_b)
    repo = Neo4jGraphIntelligenceRepository(session)

    result = await repo.get_impact(
        repository_b,
        b_nodes[1].id,
        direction=DependencyDirection.DOWNSTREAM,
        max_depth=5,
        limit=100,
    )

    assert result is not None
    assert all(n.node.repository_id == repository_b for n in result.impacted_nodes)


async def test_path_finds_the_shortest_directed_path(session: AsyncSession) -> None:
    repository_id = uuid4()
    a, b, c, d = await _seed_chain(session, repository_id)
    repo = Neo4jGraphIntelligenceRepository(session)

    result = await repo.get_path(repository_id, a.id, d.id, max_depth=6)

    assert result is not None
    assert result.found is True
    assert [n.id for n in result.nodes] == [a.id, b.id, c.id, d.id]
    assert [r.kind for r in result.relationships] == [GraphRelationshipKind.CALLS] * 3
    assert result.length == 3


async def test_path_prefers_the_shorter_of_two_routes(session: AsyncSession) -> None:
    """A -[CALLS]-> D directly, and also A -[CALLS]-> B -[CALLS]-> C -[CALLS]-> D.
    The shortest path must be the direct one-hop route."""
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    a, b, c, d = (_symbol(repository_id) for _ in range(4))
    rels = (
        _rel(repository_id, a.id, b.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, b.id, c.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, c.id, d.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, a.id, d.id, GraphRelationshipKind.CALLS),
    )
    await projector.project_repository(repository_id, (a, b, c, d), rels)
    repo = Neo4jGraphIntelligenceRepository(session)

    result = await repo.get_path(repository_id, a.id, d.id, max_depth=6)

    assert result is not None
    assert result.length == 1
    assert [n.id for n in result.nodes] == [a.id, d.id]


async def test_path_not_found_within_max_depth_is_a_valid_negative_result(
    session: AsyncSession,
) -> None:
    repository_id = uuid4()
    a, b, c, d = await _seed_chain(session, repository_id)  # A->B->C->D, length 3
    repo = Neo4jGraphIntelligenceRepository(session)

    result = await repo.get_path(repository_id, a.id, d.id, max_depth=2)  # too short to reach D

    assert result is not None
    assert result.found is False
    assert result.nodes == ()
    assert result.relationships == ()
    assert result.length is None


async def test_path_with_no_directed_route_is_not_found_even_if_reverse_exists(
    session: AsyncSession,
) -> None:
    """A -[CALLS]-> B only. A path request from B to A must be `found=False`
    — a directed search never silently falls back to an undirected one."""
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    a, b = (_symbol(repository_id) for _ in range(2))
    await projector.project_repository(
        repository_id, (a, b), (_rel(repository_id, a.id, b.id, GraphRelationshipKind.CALLS),)
    )
    repo = Neo4jGraphIntelligenceRepository(session)

    result = await repo.get_path(repository_id, b.id, a.id, max_depth=6)

    assert result is not None
    assert result.found is False


async def test_path_same_node_request_is_well_defined(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    node = _symbol(repository_id)
    await projector.project_repository(repository_id, (node,), ())
    repo = Neo4jGraphIntelligenceRepository(session)

    result = await repo.get_path(repository_id, node.id, node.id, max_depth=6)

    assert result is not None
    assert result.found is True
    assert [n.id for n in result.nodes] == [node.id]
    assert result.relationships == ()
    assert result.length == 0


async def test_path_respects_relationship_kind_filter(session: AsyncSession) -> None:
    """A -[IMPORTS]-> B -[CALLS]-> C. Restricting to CALLS only must find no
    path from A to C, since the first hop (IMPORTS) is excluded."""
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    a, b, c = (_symbol(repository_id) for _ in range(3))
    rels = (
        _rel(repository_id, a.id, b.id, GraphRelationshipKind.IMPORTS),
        _rel(repository_id, b.id, c.id, GraphRelationshipKind.CALLS),
    )
    await projector.project_repository(repository_id, (a, b, c), rels)
    repo = Neo4jGraphIntelligenceRepository(session)

    calls_only = await repo.get_path(
        repository_id, a.id, c.id, max_depth=6, kind=GraphRelationshipKind.CALLS
    )
    unrestricted = await repo.get_path(repository_id, a.id, c.id, max_depth=6)

    assert calls_only is not None
    assert calls_only.found is False
    assert unrestricted is not None
    assert unrestricted.found is True


async def test_path_returns_none_for_unknown_source_or_target(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    node = _symbol(repository_id)
    await projector.project_repository(repository_id, (node,), ())
    repo = Neo4jGraphIntelligenceRepository(session)

    assert await repo.get_path(repository_id, node.id, uuid4(), max_depth=6) is None
    assert await repo.get_path(repository_id, uuid4(), node.id, max_depth=6) is None


async def test_path_returns_none_for_cross_repository_node(session: AsyncSession) -> None:
    repository_a = uuid4()
    repository_b = uuid4()
    projector = Neo4jGraphRepository(session)
    node_in_a = _symbol(repository_a)
    node_in_b = _symbol(repository_b)
    await projector.project_repository(repository_a, (node_in_a,), ())
    await projector.project_repository(repository_b, (node_in_b,), ())
    repo = Neo4jGraphIntelligenceRepository(session)

    assert await repo.get_path(repository_b, node_in_a.id, node_in_b.id, max_depth=6) is None


async def test_statistics_counts_nodes_and_relationships_by_kind(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    a, b, c, d = (_symbol(repository_id) for _ in range(4))
    rels = (
        _rel(repository_id, a.id, b.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, b.id, c.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, c.id, d.id, GraphRelationshipKind.IMPORTS),
    )
    await projector.project_repository(
        repository_id, (_repository_node(repository_id), a, b, c, d), rels
    )
    repo = Neo4jGraphIntelligenceRepository(session)

    stats = await repo.get_statistics(repository_id, limit=10)

    assert stats.total_nodes == 5  # repository + 4 symbols
    assert stats.total_symbols == 4
    assert stats.total_files == 0
    assert stats.total_relationships == 3
    by_kind = {entry.kind: entry.count for entry in stats.relationships_by_kind}
    assert by_kind[GraphRelationshipKind.CALLS] == 2
    assert by_kind[GraphRelationshipKind.IMPORTS] == 1
    assert by_kind[GraphRelationshipKind.INHERITS] == 0  # every kind present, zero-filled
    assert by_kind[GraphRelationshipKind.CONTAINS] == 0
    assert by_kind[GraphRelationshipKind.DEFINES] == 0


async def test_statistics_degree_rankings(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    hub = _symbol(repository_id)
    leaves = [_symbol(repository_id) for _ in range(3)]
    rels = tuple(
        _rel(repository_id, hub.id, leaf.id, GraphRelationshipKind.CALLS) for leaf in leaves
    )
    await projector.project_repository(repository_id, (hub, *leaves), rels)
    repo = Neo4jGraphIntelligenceRepository(session)

    stats = await repo.get_statistics(repository_id, limit=10)

    assert stats.highest_out_degree[0].node.id == hub.id
    assert stats.highest_out_degree[0].degree == 3
    assert all(entry.degree == 1 for entry in stats.highest_in_degree)


async def test_statistics_respects_limit(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    hub = _symbol(repository_id)
    leaves = [_symbol(repository_id) for _ in range(5)]
    rels = tuple(
        _rel(repository_id, hub.id, leaf.id, GraphRelationshipKind.CALLS) for leaf in leaves
    )
    await projector.project_repository(repository_id, (hub, *leaves), rels)
    repo = Neo4jGraphIntelligenceRepository(session)

    stats = await repo.get_statistics(repository_id, limit=2)

    assert len(stats.highest_in_degree) == 2


async def test_statistics_projected_at_is_populated(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    result = await projector.project_repository(
        repository_id, (_repository_node(repository_id),), ()
    )
    repo = Neo4jGraphIntelligenceRepository(session)

    stats = await repo.get_statistics(repository_id, limit=10)

    assert stats.projected_at == result.projected_at


async def test_statistics_of_an_unprojected_repository_is_all_zero(session: AsyncSession) -> None:
    repository_id = uuid4()
    repo = Neo4jGraphIntelligenceRepository(session)

    stats = await repo.get_statistics(repository_id, limit=10)

    assert stats.total_nodes == 0
    assert stats.total_relationships == 0
    assert stats.projected_at is None
    assert all(entry.count == 0 for entry in stats.relationships_by_kind)


async def test_statistics_never_cross_contaminates_repositories(session: AsyncSession) -> None:
    repository_a = uuid4()
    repository_b = uuid4()
    projector = Neo4jGraphRepository(session)
    a1, a2 = _symbol(repository_a), _symbol(repository_a)
    await projector.project_repository(
        repository_a,
        (a1, a2),
        (_rel(repository_a, a1.id, a2.id, GraphRelationshipKind.CALLS),),
    )
    await projector.project_repository(repository_b, (_symbol(repository_b),), ())
    repo = Neo4jGraphIntelligenceRepository(session)

    stats_a = await repo.get_statistics(repository_a, limit=10)
    stats_b = await repo.get_statistics(repository_b, limit=10)

    assert stats_a.total_nodes == 2
    assert stats_a.total_relationships == 1
    assert stats_b.total_nodes == 1
    assert stats_b.total_relationships == 0


async def test_insights_most_connected_files(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    hub = _file(repository_id, "hub.py")
    leaves = [_file(repository_id, f"leaf{i}.py") for i in range(3)]
    rels = tuple(
        _rel(repository_id, hub.id, leaf.id, GraphRelationshipKind.IMPORTS) for leaf in leaves
    )
    await projector.project_repository(repository_id, (hub, *leaves), rels)
    repo = Neo4jGraphIntelligenceRepository(session)

    insights = await repo.get_insights(repository_id, limit=10)

    assert insights.most_connected_files[0].node.id == hub.id
    assert insights.most_connected_files[0].degree == 3
    # leaves each have degree 1 and are included too (degree > 0)
    assert len(insights.most_connected_files) == 4


async def test_insights_excludes_zero_degree_files_from_most_connected(
    session: AsyncSession,
) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    connected_a = _file(repository_id, "a.py")
    connected_b = _file(repository_id, "b.py")
    unconnected = _file(repository_id, "unconnected.py")
    await projector.project_repository(
        repository_id,
        (connected_a, connected_b, unconnected),
        (_rel(repository_id, connected_a.id, connected_b.id, GraphRelationshipKind.IMPORTS),),
    )
    repo = Neo4jGraphIntelligenceRepository(session)

    insights = await repo.get_insights(repository_id, limit=10)

    connected_ids = {entry.node.id for entry in insights.most_connected_files}
    assert connected_ids == {connected_a.id, connected_b.id}
    assert unconnected.id not in connected_ids


async def test_insights_dependency_hotspots_combine_calls_and_inherits(
    session: AsyncSession,
) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    hotspot = _symbol(repository_id)
    caller = _symbol(repository_id)
    subclass = _symbol(repository_id)
    rels = (
        _rel(repository_id, caller.id, hotspot.id, GraphRelationshipKind.CALLS),
        _rel(repository_id, subclass.id, hotspot.id, GraphRelationshipKind.INHERITS),
    )
    await projector.project_repository(repository_id, (hotspot, caller, subclass), rels)
    repo = Neo4jGraphIntelligenceRepository(session)

    insights = await repo.get_insights(repository_id, limit=10)

    top = insights.dependency_hotspots[0]
    assert top.node.id == hotspot.id
    assert top.degree == 2  # one CALLS + one INHERITS


async def test_insights_isolated_nodes(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    connected_file_a = _file(repository_id, "a.py")
    connected_file_b = _file(repository_id, "b.py")
    isolated_file = _file(repository_id, "isolated.py")
    connected_symbol = _symbol(repository_id)
    other_symbol = _symbol(repository_id)
    isolated_symbol = _symbol(repository_id)
    rels = (
        _rel(
            repository_id,
            connected_file_a.id,
            connected_file_b.id,
            GraphRelationshipKind.IMPORTS,
        ),
        _rel(repository_id, connected_symbol.id, other_symbol.id, GraphRelationshipKind.CALLS),
    )
    await projector.project_repository(
        repository_id,
        (
            connected_file_a,
            connected_file_b,
            isolated_file,
            connected_symbol,
            other_symbol,
            isolated_symbol,
        ),
        rels,
    )
    repo = Neo4jGraphIntelligenceRepository(session)

    insights = await repo.get_insights(repository_id, limit=10)

    isolated_ids = {n.id for n in insights.isolated_nodes}
    assert isolated_file.id in isolated_ids
    assert isolated_symbol.id in isolated_ids
    assert connected_file_a.id not in isolated_ids
    assert connected_file_b.id not in isolated_ids
    assert connected_symbol.id not in isolated_ids
    assert other_symbol.id not in isolated_ids


async def test_insights_mutual_import_pairs(session: AsyncSession) -> None:
    repository_id = uuid4()
    projector = Neo4jGraphRepository(session)
    a = _file(repository_id, "a.py")
    b = _file(repository_id, "b.py")
    c = _file(repository_id, "c.py")  # one-directional only, not mutual
    rels = (
        _rel(repository_id, a.id, b.id, GraphRelationshipKind.IMPORTS),
        _rel(repository_id, b.id, a.id, GraphRelationshipKind.IMPORTS),
        _rel(repository_id, a.id, c.id, GraphRelationshipKind.IMPORTS),
    )
    await projector.project_repository(repository_id, (a, b, c), rels)
    repo = Neo4jGraphIntelligenceRepository(session)

    insights = await repo.get_insights(repository_id, limit=10)

    assert len(insights.mutual_import_pairs) == 1
    pair = insights.mutual_import_pairs[0]
    assert {pair.file_a.id, pair.file_b.id} == {a.id, b.id}


async def test_insights_of_an_unprojected_repository_is_all_empty(session: AsyncSession) -> None:
    repository_id = uuid4()
    repo = Neo4jGraphIntelligenceRepository(session)

    insights = await repo.get_insights(repository_id, limit=10)

    assert insights.most_connected_files == ()
    assert insights.dependency_hotspots == ()
    assert insights.isolated_nodes == ()
    assert insights.mutual_import_pairs == ()
    assert insights.unresolved_dependency_count == 0  # placeholder, service overwrites this


async def test_insights_never_cross_contaminates_repositories(session: AsyncSession) -> None:
    repository_a = uuid4()
    repository_b = uuid4()
    projector = Neo4jGraphRepository(session)
    a1 = _file(repository_a, "a1.py")
    a2 = _file(repository_a, "a2.py")
    await projector.project_repository(
        repository_a,
        (a1, a2),
        (
            _rel(repository_a, a1.id, a2.id, GraphRelationshipKind.IMPORTS),
            _rel(repository_a, a2.id, a1.id, GraphRelationshipKind.IMPORTS),
        ),
    )
    await projector.project_repository(repository_b, (_file(repository_b, "b.py"),), ())
    repo = Neo4jGraphIntelligenceRepository(session)

    insights_b = await repo.get_insights(repository_b, limit=10)

    assert insights_b.mutual_import_pairs == ()
    assert insights_b.most_connected_files == ()


async def test_query_timeout_raises_graph_unavailable_error(session: AsyncSession) -> None:
    """A vanishingly small `query_timeout_seconds` must cause the whole
    `execute_read` call to be cancelled and surfaced as
    `GraphUnavailableError` — proves `asyncio.wait_for` actually bounds a
    real Neo4j call, not just that it doesn't break the happy path (see
    infrastructure/graph_intelligence/neo4j_graph_intelligence_repository.py
    module docstring)."""
    repository_id = uuid4()
    repo = Neo4jGraphIntelligenceRepository(session, query_timeout_seconds=0.0000001)

    with pytest.raises(GraphUnavailableError):
        await repo.get_statistics(repository_id, limit=10)


async def test_no_timeout_configured_runs_normally(session: AsyncSession) -> None:
    repository_id = uuid4()
    repo = Neo4jGraphIntelligenceRepository(session, query_timeout_seconds=None)

    stats = await repo.get_statistics(repository_id, limit=10)

    assert stats.total_nodes == 0
