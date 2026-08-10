"""Graph projection domain model — Phase 5.

Purpose:       Define what a "graph node" and "graph relationship" are —
                Forge's queryable Neo4j projection of already-persisted
                PostgreSQL data (Phase 3's `ParsedFile`/`Symbol`, Phase 4's
                `DependencyEdge`) — independent of the `neo4j` driver or any
                Cypher.
Responsibility: `GraphNodeKind`, `GraphNode`, `GraphRelationshipKind`,
                `GraphRelationship`, `GraphNeighbor`, `ProjectionResult`.

Why three node kinds, not more: `Repository`/`File`/`Symbol` are Forge's only
first-class entities with a stable, deterministic id — `Parameter`, `Import`
(the raw statement), and `ParseError` are display-only detail or already
fully represented once resolved (an `Import` becomes an `IMPORTS`
relationship, not a node) — see docs/architecture/05-knowledge-graph.md,
"Graph node model".

Why `Symbol` is one node kind (not FUNCTION/CLASS/METHOD each a separate
label): mirrors Phase 3's own `Symbol` dataclass, which already collapsed the
same three kinds into one entity distinguished by a `kind` field, not three
classes. `GraphNode.symbol_kind` carries that same distinction as a property,
never as a separate Neo4j label — a direct instruction from the Phase 5 brief.

Why relationships carry `repository_id` (and, for dependency-derived kinds,
`dependency_edge_id`) as properties: every graph query must be able to scope
to one repository without a traversal (see domain/graph/ports.py), and every
projected fact must be traceable back to the PostgreSQL row it came from —
Neo4j is a derived projection, never the only copy of anything.

Depends on:    stdlib only.
Depended on by: domain/graph/ports.py, infrastructure/graph/*.py,
                application/graph/service.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class GraphNodeKind(StrEnum):
    """The Neo4j label a `GraphNode` is projected as."""

    REPOSITORY = "repository"
    FILE = "file"
    SYMBOL = "symbol"


class GraphRelationshipKind(StrEnum):
    """The Neo4j relationship type a `GraphRelationship` is projected as.

    CONTAINS and DEFINES are structural (Repository->File, File->Symbol,
    and CLASS Symbol->METHOD Symbol) — always derivable, never unresolved.
    IMPORTS/CALLS/INHERITS mirror `domain/dependency_analysis/entities.py::DependencyKind`
    by name, but only ever projected for a `DependencyEdge` whose
    `resolution_status` is RESOLVED — see application/graph/service.py.

    REFERENCES is deliberately NOT declared here: Phase 4 defines
    `DependencyKind.REFERENCES` for forward extensibility but no resolver
    currently produces it — there is no data to project (verified directly
    against `DependencyAnalysisService`). Adding it now would be exactly the
    "blindly implement every relationship" the Phase 5 brief warns against.
    """

    CONTAINS = "contains"
    DEFINES = "defines"
    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One node to project into Neo4j.

    Attributes:
        id: Forge's existing PostgreSQL id for the underlying entity
            (`Repository.id`, `ParsedFile.id`, or `Symbol.id`) — used
            directly as the Neo4j node's `id` property and `MERGE` key.
            Never a Neo4j-internal id (`elementId()`/`id()`); see
            domain/graph/ports.py.
        kind: Which label this node is projected as.
        repository_id: The owning `Repository`'s id — present on every node,
            including `Repository` nodes themselves (where it equals `id`),
            so every Cypher query can filter on the node directly.
        properties: Every other Neo4j property, already primitive
            (str/int/bool/None) — no domain dataclass, tree-sitter, or SQLAlchemy
            type ever crosses into this dict.
    """

    id: UUID
    kind: GraphNodeKind
    repository_id: UUID
    properties: dict[str, str | int | bool | None]


@dataclass(frozen=True, slots=True)
class GraphRelationship:
    """One relationship to project into Neo4j.

    Attributes:
        source_id: The id of the node this relationship starts from.
        target_id: The id of the node this relationship points to.
        kind: Which relationship type this is projected as.
        repository_id: The owning `Repository`'s id — present on every
            relationship for the same query-scoping reason as `GraphNode`.
        dependency_edge_id: The originating `DependencyEdge.id` (Phase 4),
            for IMPORTS/CALLS/INHERITS only — `None` for the purely
            structural CONTAINS/DEFINES kinds, which have no Phase 4 row to
            trace back to.
        properties: Every other Neo4j relationship property, already
            primitive.
    """

    source_id: UUID
    target_id: UUID
    kind: GraphRelationshipKind
    repository_id: UUID
    dependency_edge_id: UUID | None
    properties: dict[str, str | int | bool | None]


@dataclass(frozen=True, slots=True)
class GraphNeighbor:
    """One neighbor of a queried node, with the relationship that connects them.

    Attributes:
        node: The neighboring node.
        relationship_kind: How it connects to the queried node.
        direction: `"outgoing"` if the queried node is the relationship's
            source, `"incoming"` if it's the target.
    """

    node: GraphNode
    relationship_kind: GraphRelationshipKind
    direction: str


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """The outcome of projecting one repository's graph.

    Attributes:
        repository_id: The `Repository` that was projected.
        node_count: Total nodes written.
        relationship_count: Total relationships written.
        projected_at: When this projection run completed (UTC).
    """

    repository_id: UUID
    node_count: int
    relationship_count: int
    projected_at: datetime
