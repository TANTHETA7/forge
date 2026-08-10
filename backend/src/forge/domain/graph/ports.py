"""Ports the graph-projection workflow depends on, implemented by
infrastructure and injected into `application/graph/service.py`.

Purpose:       Let the application layer project a repository's graph and
                query it back without importing the `neo4j` driver, Cypher,
                or any Neo4j-specific type directly — the same "application
                depends on abstractions, infrastructure implements them" rule
                every earlier phase already established (see
                domain/parsing/ports.py, domain/dependency_analysis/ports.py).
Responsibility: One interface, `GraphRepository` — combining projection
                (write) and query (read) methods in a single Protocol,
                deliberately mirroring `ParsedFileRepository`'s and
                `DependencyEdgeRepository`'s own shape (both already mix
                `save_*`/`get_*` in one Protocol) rather than inventing a new
                write/read split Forge doesn't use anywhere else.
Depends on:    domain/graph/entities.py.
Depended on by: application/graph/service.py; implemented by
                infrastructure/graph/neo4j_graph_repository.py.
"""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from forge.domain.graph.entities import (
    GraphNeighbor,
    GraphNode,
    GraphNodeKind,
    GraphRelationship,
    GraphRelationshipKind,
    ProjectionResult,
)


class GraphRepository(Protocol):
    """Persistence port for a repository's Neo4j graph projection.

    Every method is scoped to one `repository_id`, passed explicitly and
    always sourced from server-side/path data (never client-controlled
    request-body fields) — this is what makes repository isolation a
    property of every call, not something callers have to separately
    remember to enforce (see docs/architecture/05-knowledge-graph.md,
    "Repository isolation").
    """

    async def project_repository(
        self,
        repository_id: UUID,
        nodes: tuple[GraphNode, ...],
        relationships: tuple[GraphRelationship, ...],
    ) -> ProjectionResult:
        """Replace `repository_id`'s entire graph projection with `nodes`/
        `relationships` — delete every previously-projected node and
        relationship for this repository, then write the new set. Never
        touches any other repository's data. Idempotent: calling this twice
        with the same `nodes`/`relationships` produces an identical graph,
        not duplicates (see docs/architecture/05-knowledge-graph.md,
        "Projection lifecycle")."""
        ...

    async def get_nodes(
        self,
        repository_id: UUID,
        *,
        kind: GraphNodeKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GraphNode]:
        """Nodes for `repository_id`, optionally filtered by `kind`,
        paginated. Empty list if nothing has been projected yet — not an
        error."""
        ...

    async def get_relationships(
        self,
        repository_id: UUID,
        *,
        kind: GraphRelationshipKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GraphRelationship]:
        """Relationships for `repository_id`, optionally filtered by `kind`,
        paginated."""
        ...

    async def get_neighbors(
        self,
        repository_id: UUID,
        node_id: UUID,
        *,
        direction: Literal["incoming", "outgoing", "both"] = "both",
        kind: GraphRelationshipKind | None = None,
        limit: int = 100,
    ) -> list[GraphNeighbor] | None:
        """Direct neighbors of `node_id`, or `None` if `node_id` doesn't
        exist *within this repository* — a node_id that exists but belongs
        to a different repository is indistinguishable from one that doesn't
        exist at all, by design (see docs/architecture/05-knowledge-graph.md,
        "Security" / cross-repository query attempts).

        `kind` optionally restricts which relationship type connects a
        neighbor — added in Phase 6 (docs/architecture/06-code-intelligence.md)
        to support dependency/dependent exploration filtered by relationship
        kind, without a second single-hop traversal query. `None` (the
        default) preserves Phase 5's original behavior of returning every
        adjacent relationship regardless of type."""
        ...

    async def is_available(self) -> bool:
        """Whether Neo4j is currently reachable — used to fail a projection
        attempt fast, with a clear `GraphUnavailableError`, rather than
        letting a raw driver exception surface."""
        ...
