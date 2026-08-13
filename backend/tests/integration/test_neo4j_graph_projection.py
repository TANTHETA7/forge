"""End-to-end test of `Neo4jGraphRepository` against a REAL Neo4j instance —
not a fake, for the same reason the Postgres-persistence tests use a real
`asyncpg`/SQLAlchemy connection: constraint/idempotency/isolation behavior
only surfaces against the real backend.

Uses the shared `neo4j_graph` fixture from tests/integration/conftest.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest_asyncio
from neo4j import AsyncGraphDatabase, AsyncSession

from forge.domain.graph.entities import (
    GraphNode,
    GraphNodeKind,
    GraphRelationship,
    GraphRelationshipKind,
)
from forge.infrastructure.graph.neo4j_driver import ensure_constraints
from forge.infrastructure.graph.neo4j_graph_repository import Neo4jGraphRepository
from tests.integration.conftest import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER


@pytest_asyncio.fixture
async def session(neo4j_graph: None) -> AsyncIterator[AsyncSession]:
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    async with driver.session() as session_:
        yield session_
    await driver.close()


def _file_node(repository_id: UUID, path: str) -> GraphNode:
    return GraphNode(
        id=uuid4(),
        kind=GraphNodeKind.FILE,
        repository_id=repository_id,
        properties={"path": path, "language": "python", "has_syntax_errors": False},
    )


def _repository_node(repository_id: UUID) -> GraphNode:
    return GraphNode(
        id=repository_id,
        kind=GraphNodeKind.REPOSITORY,
        repository_id=repository_id,
        properties={"project_id": str(uuid4()), "display_name": "fixture"},
    )


def _contains(repository_id: UUID, source_id: UUID, target_id: UUID) -> GraphRelationship:
    return GraphRelationship(
        source_id=source_id,
        target_id=target_id,
        kind=GraphRelationshipKind.CONTAINS,
        repository_id=repository_id,
        dependency_edge_id=None,
        properties={},
    )


def _imports(
    repository_id: UUID, source_id: UUID, target_id: UUID, dependency_edge_id: UUID
) -> GraphRelationship:
    return GraphRelationship(
        source_id=source_id,
        target_id=target_id,
        kind=GraphRelationshipKind.IMPORTS,
        repository_id=repository_id,
        dependency_edge_id=dependency_edge_id,
        properties={"raw_target_expression": ".utils"},
    )


async def test_constraints_are_idempotent(session: AsyncSession) -> None:
    from forge.core.config import Settings

    settings = Settings(
        neo4j_uri=NEO4J_URI, neo4j_user=NEO4J_USER, neo4j_password=NEO4J_PASSWORD
    )
    await ensure_constraints(settings)
    await ensure_constraints(settings)  # must not raise on the second call

    result = await session.run("SHOW CONSTRAINTS YIELD name RETURN name")
    names = {record["name"] async for record in result}
    assert {"repository_id_unique", "file_id_unique", "symbol_id_unique"} <= names


async def test_projects_nodes_and_relationships(session: AsyncSession) -> None:
    repo = Neo4jGraphRepository(session)
    repository_id = uuid4()
    repo_node = _repository_node(repository_id)
    file_a = _file_node(repository_id, "a.py")
    file_b = _file_node(repository_id, "b.py")
    nodes = (repo_node, file_a, file_b)
    relationships = (
        _contains(repository_id, repository_id, file_a.id),
        _contains(repository_id, repository_id, file_b.id),
        _imports(repository_id, file_a.id, file_b.id, uuid4()),
    )

    result = await repo.project_repository(repository_id, nodes, relationships)

    assert result.node_count == 3
    assert result.relationship_count == 3
    persisted_nodes = await repo.get_nodes(repository_id)
    assert len(persisted_nodes) == 3
    persisted_relationships = await repo.get_relationships(repository_id)
    assert len(persisted_relationships) == 3


async def test_reprojection_is_idempotent_not_duplicating(session: AsyncSession) -> None:
    repo = Neo4jGraphRepository(session)
    repository_id = uuid4()
    file_a = _file_node(repository_id, "a.py")
    nodes = (_repository_node(repository_id), file_a)
    relationships = (_contains(repository_id, repository_id, file_a.id),)

    await repo.project_repository(repository_id, nodes, relationships)
    await repo.project_repository(repository_id, nodes, relationships)  # re-run, unchanged input

    assert len(await repo.get_nodes(repository_id)) == 2
    assert len(await repo.get_relationships(repository_id)) == 1


async def test_rebuild_removes_stale_nodes(session: AsyncSession) -> None:
    repo = Neo4jGraphRepository(session)
    repository_id = uuid4()
    file_a = _file_node(repository_id, "a.py")
    file_b = _file_node(repository_id, "b.py")
    first_nodes = (_repository_node(repository_id), file_a, file_b)
    await repo.project_repository(repository_id, first_nodes, ())
    assert len(await repo.get_nodes(repository_id)) == 3

    # Simulate a re-parse that removed b.py: project again without it.
    second_nodes = (_repository_node(repository_id), file_a)
    await repo.project_repository(repository_id, second_nodes, ())

    remaining = await repo.get_nodes(repository_id)
    assert {n.id for n in remaining} == {repository_id, file_a.id}


async def test_two_repositories_never_cross_contaminate(session: AsyncSession) -> None:
    repo = Neo4jGraphRepository(session)
    repository_a = uuid4()
    repository_b = uuid4()
    await repo.project_repository(
        repository_a, (_repository_node(repository_a), _file_node(repository_a, "a.py")), ()
    )
    await repo.project_repository(
        repository_b, (_repository_node(repository_b), _file_node(repository_b, "b.py")), ()
    )

    nodes_a = await repo.get_nodes(repository_a)
    nodes_b = await repo.get_nodes(repository_b)
    assert len(nodes_a) == 2
    assert len(nodes_b) == 2
    assert {n.repository_id for n in nodes_a} == {repository_a}
    assert {n.repository_id for n in nodes_b} == {repository_b}

    # Deleting/rebuilding repository A must never touch repository B's graph.
    await repo.project_repository(repository_a, (_repository_node(repository_a),), ())
    assert len(await repo.get_nodes(repository_b)) == 2


async def test_get_neighbors_returns_none_for_unknown_node(session: AsyncSession) -> None:
    repo = Neo4jGraphRepository(session)
    repository_id = uuid4()
    await repo.project_repository(
        repository_id, (_repository_node(repository_id),), ()
    )

    assert await repo.get_neighbors(repository_id, uuid4()) is None


async def test_get_neighbors_returns_none_for_cross_repository_node(session: AsyncSession) -> None:
    repo = Neo4jGraphRepository(session)
    repository_a = uuid4()
    repository_b = uuid4()
    file_in_a = _file_node(repository_a, "a.py")
    await repo.project_repository(
        repository_a, (_repository_node(repository_a), file_in_a), ()
    )
    await repo.project_repository(repository_b, (_repository_node(repository_b),), ())

    # file_in_a's id is real, but queried under repository_b's scope.
    assert await repo.get_neighbors(repository_b, file_in_a.id) is None


async def test_get_neighbors_returns_connected_nodes(session: AsyncSession) -> None:
    repo = Neo4jGraphRepository(session)
    repository_id = uuid4()
    file_a = _file_node(repository_id, "a.py")
    file_b = _file_node(repository_id, "b.py")
    await repo.project_repository(
        repository_id,
        (_repository_node(repository_id), file_a, file_b),
        (
            _contains(repository_id, repository_id, file_a.id),
            _imports(repository_id, file_a.id, file_b.id, uuid4()),
        ),
    )

    outgoing = await repo.get_neighbors(repository_id, file_a.id, direction="outgoing")
    assert outgoing is not None
    assert [n.node.id for n in outgoing] == [file_b.id]
    assert outgoing[0].relationship_kind is GraphRelationshipKind.IMPORTS
    assert outgoing[0].direction == "outgoing"

    incoming = await repo.get_neighbors(repository_id, file_b.id, direction="incoming")
    assert incoming is not None
    assert [n.node.id for n in incoming] == [file_a.id]
    assert incoming[0].direction == "incoming"

    both = await repo.get_neighbors(repository_id, file_a.id, direction="both")
    assert both is not None
    assert {n.node.id for n in both} == {repository_id, file_b.id}


async def test_get_neighbors_filters_by_relationship_kind(session: AsyncSession) -> None:
    """Added in Phase 6 (docs/architecture/06-code-intelligence.md) to
    support kind-filtered dependency/dependent exploration without a second
    traversal query — `kind=None` (the default) preserves Phase 5's
    original unfiltered behavior, verified in the "both" branch below."""
    repo = Neo4jGraphRepository(session)
    repository_id = uuid4()
    file_a = _file_node(repository_id, "a.py")
    file_b = _file_node(repository_id, "b.py")
    await repo.project_repository(
        repository_id,
        (_repository_node(repository_id), file_a, file_b),
        (
            _contains(repository_id, repository_id, file_a.id),
            _imports(repository_id, file_a.id, file_b.id, uuid4()),
        ),
    )

    imports_only = await repo.get_neighbors(
        repository_id, file_a.id, direction="outgoing", kind=GraphRelationshipKind.IMPORTS
    )
    assert imports_only is not None
    assert [n.node.id for n in imports_only] == [file_b.id]

    contains_only = await repo.get_neighbors(
        repository_id, file_a.id, direction="outgoing", kind=GraphRelationshipKind.CONTAINS
    )
    assert contains_only == []  # file_a has no outgoing CONTAINS relationship

    unfiltered = await repo.get_neighbors(repository_id, file_a.id, direction="outgoing")
    assert unfiltered is not None
    assert [n.node.id for n in unfiltered] == [file_b.id]  # kind=None: unchanged behavior


async def test_is_available_reports_true_against_real_neo4j(session: AsyncSession) -> None:
    repo = Neo4jGraphRepository(session)
    assert await repo.is_available() is True


async def test_deterministic_ids_are_stable_across_runs(session: AsyncSession) -> None:
    repo = Neo4jGraphRepository(session)
    repository_id = uuid4()
    file_a = _file_node(repository_id, "a.py")
    nodes = (_repository_node(repository_id), file_a)

    first = await repo.project_repository(repository_id, nodes, ())
    second = await repo.project_repository(repository_id, nodes, ())

    assert first.node_count == second.node_count
    persisted = await repo.get_nodes(repository_id)
    assert {n.id for n in persisted} == {repository_id, file_a.id}


def _plan_operator_types(plan: object) -> set[str]:
    """Flatten a Neo4j `ResultSummary.plan`'s operator tree into the set of
    every `operatorType` it contains, recursing through `children` — used to
    assert an operator (e.g. `AllNodesScan`) never appears anywhere in the
    plan, not just at the root."""
    if not isinstance(plan, dict):
        return set()
    types = {str(plan["operatorType"])} if "operatorType" in plan else set()
    for child in plan.get("children", ()):
        types |= _plan_operator_types(child)
    return types


async def test_relationship_projection_never_falls_back_to_a_full_node_scan(
    session: AsyncSession,
) -> None:
    # Regression test for a real, severe bug found validating Forge against
    # scrapy/scrapy (476 files): the relationship-write query's `MATCH (a
    # {id: ...}), (b {id: ...})` had no node label, so Neo4j could not use
    # any label-scoped index and fell back to `AllNodesScan` — confirmed via
    # `EXPLAIN` against a real database (`AllNodesScan` over 133,627 nodes,
    # in a `CartesianProduct`, for *every row* of the relationship-write
    # `UNWIND`) and via a live `SHOW TRANSACTIONS` (one single
    # graph-projection query still running after 5m44s against a 476-file
    # repository). A plan-shape assertion catches a regression back to this
    # deterministically — no timing/flakiness risk — where a wall-clock
    # timing test would need many thousands of pre-existing nodes to
    # reliably distinguish "slow" from "hung" and would be slow itself.
    query = (
        "EXPLAIN UNWIND [{source_id: 'x', target_id: 'y', repository_id: 'z', "
        "dependency_edge_id: 'w'}] AS row "
        "MATCH (a:Node {id: row.source_id, repository_id: row.repository_id}), "
        "(b:Node {id: row.target_id, repository_id: row.repository_id}) "
        "MERGE (a)-[r:IMPORTS {dependency_edge_id: row.dependency_edge_id}]->(b) "
        "SET r += row"
    )
    result = await session.run(query)
    summary = await result.consume()

    operator_types = _plan_operator_types(summary.plan)
    assert "AllNodesScan" not in operator_types
    assert any("IndexSeek" in op for op in operator_types)


async def test_get_relationships_pagination_is_stable_with_many_edges_between_the_same_pair(
    session: AsyncSession,
) -> None:
    # Regression test for a real bug found validating Forge against
    # pytest-dev/pytest: `get_relationships` ordered by `source_id, target_id`
    # only — not unique when many distinct relationships connect the exact
    # same two nodes (confirmed empirically there: some symbol pairs have 19
    # CALLS relationships between them, one per call site). `SKIP`/`LIMIT`
    # alone is not guaranteed to see the same tie-order across two separate
    # query executions. Every relationship here connects the identical
    # (source, target) pair, forcing every page boundary to fall inside a
    # tie — exactly the condition that reproduces the bug.
    repo = Neo4jGraphRepository(session)
    repository_id = uuid4()
    file_a = _file_node(repository_id, "a.py")
    file_b = _file_node(repository_id, "b.py")
    count = 40
    page_size = 15
    relationships = tuple(
        _imports(repository_id, file_a.id, file_b.id, uuid4()) for _ in range(count)
    )
    await repo.project_repository(
        repository_id, (_repository_node(repository_id), file_a, file_b), relationships
    )

    drained: list[GraphRelationship] = []
    offset = 0
    while True:
        page = await repo.get_relationships(repository_id, limit=page_size, offset=offset)
        drained.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    assert len(drained) == count  # none dropped, none duplicated across the page boundary
    dependency_edge_ids = {r.dependency_edge_id for r in drained}
    assert len(dependency_edge_ids) == count  # every underlying edge distinct
    assert dependency_edge_ids == {r.dependency_edge_id for r in relationships}


async def test_projected_at_is_stamped_on_the_repository_node(session: AsyncSession) -> None:
    """Added in Phase 6 (docs/architecture/06-code-intelligence.md, "Graph
    freshness") — a small, additive Phase 5 touch: `project_repository`
    writes when it ran onto the `:Repository` node so a later statistics
    query can tell whether the graph is current relative to PostgreSQL."""
    repo = Neo4jGraphRepository(session)
    repository_id = uuid4()

    result = await repo.project_repository(repository_id, (_repository_node(repository_id),), ())

    [repository_node] = await repo.get_nodes(repository_id, kind=GraphNodeKind.REPOSITORY)
    stored = repository_node.properties["projected_at"]
    assert isinstance(stored, str)
    assert stored == result.projected_at.isoformat()
