"""Neo4j implementation of `domain/graph/ports.py::GraphRepository`.

Purpose:       Persist and query a repository's graph projection in Neo4j.
Responsibility: Translate between the domain entities (`GraphNode`/
                `GraphRelationship`) and Cypher only — no resolution/mapping
                logic (that's infrastructure/graph/graph_mapping.py), no
                application orchestration. Every query here is a fixed,
                parameterized template; the only per-call variation in the
                query *text* itself is a node label or relationship type
                selected from this module's own internal, trusted
                `_NODE_LABEL`/`_REL_TYPE` maps — never a raw client-supplied
                string (see docs/architecture/05-knowledge-graph.md,
                "Security").
Depends on:    neo4j, domain/graph/{entities,ports}.py, domain/errors.py.
Depended on by: infrastructure/graph/dependencies.py-equivalent DI wiring in
                api/graph.py.

Every write and read goes through `execute_write`/`execute_read` (the
driver's managed-transaction API) — never a bare `session.run` outside one —
so the driver's built-in retry behavior for transient/leader errors applies
automatically; no custom retry loop is written here.

Every node/relationship's PostgreSQL UUID is sent to Neo4j as a plain string
(the Bolt protocol has no native UUID type) and parsed back with `UUID(...)`
on read — Neo4j's own internal `elementId()`/`id()` is never read, stored, or
treated as a Forge identity anywhere in this module.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from neo4j import AsyncManagedTransaction, AsyncSession, Record

from forge.domain.errors import GraphUnavailableError
from forge.domain.graph.entities import (
    GraphNeighbor,
    GraphNode,
    GraphNodeKind,
    GraphRelationship,
    GraphRelationshipKind,
    ProjectionResult,
)
from forge.infrastructure.graph.neo4j_driver import UNAVAILABLE_EXCEPTIONS

_NODE_LABEL: dict[GraphNodeKind, str] = {
    GraphNodeKind.REPOSITORY: "Repository",
    GraphNodeKind.FILE: "File",
    GraphNodeKind.SYMBOL: "Symbol",
}
_LABEL_TO_KIND = {label: kind for kind, label in _NODE_LABEL.items()}

_REL_TYPE: dict[GraphRelationshipKind, str] = {
    GraphRelationshipKind.CONTAINS: "CONTAINS",
    GraphRelationshipKind.DEFINES: "DEFINES",
    GraphRelationshipKind.IMPORTS: "IMPORTS",
    GraphRelationshipKind.CALLS: "CALLS",
    GraphRelationshipKind.INHERITS: "INHERITS",
}
_TYPE_TO_KIND = {rel_type: kind for kind, rel_type in _REL_TYPE.items()}

# Relationship kinds that trace back to a Phase 4 DependencyEdge — their MERGE
# key includes `dependency_edge_id`, so two distinct Postgres edges between
# the same two nodes (e.g. two separate `from x import a` / `from x import b`
# statements resolving to the same file pair) become two distinct
# relationships, each traceable to its own row, never silently collapsed.
# CONTAINS/DEFINES have no such row (`dependency_edge_id` is always `None`)
# and are structurally unique per (source, target) pair already.
_DEPENDENCY_DERIVED_KINDS = frozenset(
    {GraphRelationshipKind.IMPORTS, GraphRelationshipKind.CALLS, GraphRelationshipKind.INHERITS}
)

_NEIGHBOR_QUERIES: dict[str, str] = {
    "outgoing": (
        "MATCH (n {id: $node_id, repository_id: $repository_id}) "
        "MATCH (n)-[r]->(m) "
        "RETURN m, labels(m) AS labels, type(r) AS rel_type, 'outgoing' AS direction "
        "ORDER BY m.id LIMIT $limit"
    ),
    "incoming": (
        "MATCH (n {id: $node_id, repository_id: $repository_id}) "
        "MATCH (n)<-[r]-(m) "
        "RETURN m, labels(m) AS labels, type(r) AS rel_type, 'incoming' AS direction "
        "ORDER BY m.id LIMIT $limit"
    ),
    "both": (
        "MATCH (n {id: $node_id, repository_id: $repository_id}) "
        "MATCH (n)-[r]-(m) "
        "RETURN m, labels(m) AS labels, type(r) AS rel_type, "
        "CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END AS direction "
        "ORDER BY m.id LIMIT $limit"
    ),
}


class Neo4jGraphRepository:
    """A `GraphRepository` backed by Neo4j via the async driver."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def project_repository(
        self,
        repository_id: UUID,
        nodes: tuple[GraphNode, ...],
        relationships: tuple[GraphRelationship, ...],
    ) -> ProjectionResult:
        try:
            await self._session.execute_write(_delete_repository_graph_tx, repository_id)
            await self._session.execute_write(
                _write_nodes_and_relationships_tx, nodes, relationships
            )
        except UNAVAILABLE_EXCEPTIONS as exc:
            raise GraphUnavailableError(
                f"Neo4j unavailable while projecting repository {repository_id}: {exc}"
            ) from exc
        return ProjectionResult(
            repository_id=repository_id,
            node_count=len(nodes),
            relationship_count=len(relationships),
            projected_at=datetime.now(UTC),
        )

    async def get_nodes(
        self,
        repository_id: UUID,
        *,
        kind: GraphNodeKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GraphNode]:
        try:
            return await self._session.execute_read(
                _get_nodes_tx, repository_id, kind, limit, offset
            )
        except UNAVAILABLE_EXCEPTIONS as exc:
            raise GraphUnavailableError(f"Neo4j unavailable: {exc}") from exc

    async def get_relationships(
        self,
        repository_id: UUID,
        *,
        kind: GraphRelationshipKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GraphRelationship]:
        try:
            return await self._session.execute_read(
                _get_relationships_tx, repository_id, kind, limit, offset
            )
        except UNAVAILABLE_EXCEPTIONS as exc:
            raise GraphUnavailableError(f"Neo4j unavailable: {exc}") from exc

    async def get_neighbors(
        self,
        repository_id: UUID,
        node_id: UUID,
        *,
        direction: Literal["incoming", "outgoing", "both"] = "both",
        limit: int = 100,
    ) -> list[GraphNeighbor] | None:
        try:
            return await self._session.execute_read(
                _get_neighbors_tx, repository_id, node_id, direction, limit
            )
        except UNAVAILABLE_EXCEPTIONS as exc:
            raise GraphUnavailableError(f"Neo4j unavailable: {exc}") from exc

    async def is_available(self) -> bool:
        try:
            result = await self._session.run("RETURN 1")
            await result.consume()
        except UNAVAILABLE_EXCEPTIONS:
            return False
        return True


async def _delete_repository_graph_tx(tx: AsyncManagedTransaction, repository_id: UUID) -> None:
    """Remove every node (and, via DETACH, every relationship touching one)
    previously projected for `repository_id` — and nothing belonging to any
    other repository, since the match is unconditionally scoped by
    `repository_id`."""
    await tx.run(
        "MATCH (n {repository_id: $repository_id}) DETACH DELETE n",
        repository_id=str(repository_id),
    )


async def _write_nodes_and_relationships_tx(
    tx: AsyncManagedTransaction,
    nodes: tuple[GraphNode, ...],
    relationships: tuple[GraphRelationship, ...],
) -> None:
    nodes_by_label: dict[GraphNodeKind, list[dict[str, object]]] = defaultdict(list)
    for node in nodes:
        nodes_by_label[node.kind].append(_node_row(node))
    for node_kind, rows in nodes_by_label.items():
        label = _NODE_LABEL[node_kind]
        await tx.run(
            f"UNWIND $rows AS row MERGE (x:{label} {{id: row.id}}) SET x += row", rows=rows
        )

    relationships_by_kind: dict[GraphRelationshipKind, list[dict[str, object]]] = defaultdict(
        list
    )
    for relationship in relationships:
        relationships_by_kind[relationship.kind].append(_relationship_row(relationship))
    for rel_kind, rows in relationships_by_kind.items():
        rel_type = _REL_TYPE[rel_kind]
        merge_key = (
            "{dependency_edge_id: row.dependency_edge_id}"
            if rel_kind in _DEPENDENCY_DERIVED_KINDS
            else ""
        )
        await tx.run(
            "UNWIND $rows AS row "
            "MATCH (a {id: row.source_id, repository_id: row.repository_id}), "
            "(b {id: row.target_id, repository_id: row.repository_id}) "
            f"MERGE (a)-[r:{rel_type} {merge_key}]->(b) "
            "SET r += row",
            rows=rows,
        )


async def _get_nodes_tx(
    tx: AsyncManagedTransaction,
    repository_id: UUID,
    kind: GraphNodeKind | None,
    limit: int,
    offset: int,
) -> list[GraphNode]:
    label = f":{_NODE_LABEL[kind]}" if kind is not None else ""
    query = (
        f"MATCH (n{label} {{repository_id: $repository_id}}) "
        "RETURN n, labels(n) AS labels "
        "ORDER BY n.id SKIP $offset LIMIT $limit"
    )
    result = await tx.run(query, repository_id=str(repository_id), offset=offset, limit=limit)
    # Deliberately NOT `result.data()`: `.data()` recursively serializes a
    # `Relationship` into a `(start, type, end)` tuple (dropping its own
    # properties) — safe for `Node` values but not for `Relationship` ones
    # (see `_get_relationships_tx` below), so every read here iterates raw
    # `Record`s and converts the graph objects itself via `dict(...)`, which
    # *does* give a `Node`'s/`Relationship`'s own property mapping.
    return [_record_to_node(dict(record["n"]), record["labels"]) async for record in result]


async def _get_relationships_tx(
    tx: AsyncManagedTransaction,
    repository_id: UUID,
    kind: GraphRelationshipKind | None,
    limit: int,
    offset: int,
) -> list[GraphRelationship]:
    rel_type = f":{_REL_TYPE[kind]}" if kind is not None else ""
    query = (
        f"MATCH (a)-[r{rel_type} {{repository_id: $repository_id}}]->(b) "
        "RETURN a.id AS source_id, b.id AS target_id, r, type(r) AS rel_type "
        "ORDER BY source_id, target_id SKIP $offset LIMIT $limit"
    )
    result = await tx.run(query, repository_id=str(repository_id), offset=offset, limit=limit)
    return [_record_to_relationship(record) async for record in result]


async def _get_neighbors_tx(
    tx: AsyncManagedTransaction,
    repository_id: UUID,
    node_id: UUID,
    direction: str,
    limit: int,
) -> list[GraphNeighbor] | None:
    exists_result = await tx.run(
        "MATCH (n {id: $node_id, repository_id: $repository_id}) RETURN n LIMIT 1",
        node_id=str(node_id),
        repository_id=str(repository_id),
    )
    if await exists_result.single() is None:
        # Either node_id doesn't exist at all, or it exists but belongs to a
        # different repository — deliberately indistinguishable (see
        # domain/graph/ports.py::GraphRepository.get_neighbors).
        return None

    result = await tx.run(
        _NEIGHBOR_QUERIES[direction],
        node_id=str(node_id),
        repository_id=str(repository_id),
        limit=limit,
    )
    neighbors = []
    async for record in result:
        node = _record_to_node(dict(record["m"]), record["labels"])
        neighbors.append(
            GraphNeighbor(
                node=node,
                relationship_kind=_TYPE_TO_KIND[record["rel_type"]],
                direction=record["direction"],
            )
        )
    return neighbors


def _node_row(node: GraphNode) -> dict[str, object]:
    row: dict[str, object] = {"id": str(node.id), "repository_id": str(node.repository_id)}
    row.update(node.properties)
    return row


def _relationship_row(relationship: GraphRelationship) -> dict[str, object]:
    row: dict[str, object] = {
        "source_id": str(relationship.source_id),
        "target_id": str(relationship.target_id),
        "repository_id": str(relationship.repository_id),
        "dependency_edge_id": (
            str(relationship.dependency_edge_id)
            if relationship.dependency_edge_id is not None
            else None
        ),
    }
    row.update(relationship.properties)
    return row


def _record_to_node(node_data: dict[str, object], labels: list[str]) -> GraphNode:
    properties = dict(node_data)
    node_id = UUID(str(properties.pop("id")))
    repository_id = UUID(str(properties.pop("repository_id")))
    kind = next(_LABEL_TO_KIND[label] for label in labels if label in _LABEL_TO_KIND)
    return GraphNode(
        id=node_id, kind=kind, repository_id=repository_id, properties=_as_property_dict(properties)
    )


def _record_to_relationship(record: Record) -> GraphRelationship:
    properties: dict[str, object] = dict(record["r"])
    properties.pop("source_id", None)
    properties.pop("target_id", None)
    repository_id = UUID(str(properties.pop("repository_id")))
    raw_dependency_edge_id = properties.pop("dependency_edge_id", None)
    return GraphRelationship(
        source_id=UUID(str(record["source_id"])),
        target_id=UUID(str(record["target_id"])),
        kind=_TYPE_TO_KIND[str(record["rel_type"])],
        repository_id=repository_id,
        dependency_edge_id=UUID(str(raw_dependency_edge_id))
        if raw_dependency_edge_id is not None
        else None,
        properties=_as_property_dict(properties),
    )


def _as_property_dict(raw: dict[str, object]) -> dict[str, str | int | bool | None]:
    """Neo4j only ever stores/returns the primitive property types
    `GraphNode.properties`/`GraphRelationship.properties` are already typed
    as — this narrows the driver's `object`-typed record values back to that
    contract without a blanket `type: ignore`."""
    result: dict[str, str | int | bool | None] = {}
    for key, value in raw.items():
        assert value is None or isinstance(value, str | int | bool)
        result[key] = value
    return result
