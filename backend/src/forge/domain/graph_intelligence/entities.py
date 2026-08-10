"""Code-intelligence domain model — Phase 6.

Purpose:       Define what "dependency direction", "impact", "dependency
                path", "graph statistics", and "repository insights" mean —
                Forge's deterministic, graph-based query/analysis layer over
                Phase 5's Neo4j projection — independent of Cypher or the
                `neo4j` driver.
Responsibility: `DependencyDirection`, `ImpactedNode`, `ImpactAnalysisResult`,
                `DependencyPathResult`, `RelationshipKindCount`, `NodeDegree`,
                `GraphStatistics`, `MutualImportPair`, `GraphInsights`.

Why dependencies/dependents have no dedicated result entity here: they reuse
`domain/graph/entities.py::GraphNeighbor` (node, relationship_kind,
direction) as-is — a new `DependencyResult` would duplicate that exact shape
with no behavioral difference. Phase 6 only adds the `DependencyDirection`
vocabulary (UPSTREAM/DOWNSTREAM) on top, translated to Phase 5's existing
`"incoming"/"outgoing"` at the application layer (see
application/graph_intelligence/service.py) — see
docs/architecture/06-code-intelligence.md, "Domain model".

Depends on:    domain/graph/entities.py (SourceLocation-adjacent reuse:
                GraphNode, GraphRelationship, GraphNeighbor,
                GraphRelationshipKind).
Depended on by: domain/graph_intelligence/ports.py, infrastructure/
                graph_intelligence/*.py, application/graph_intelligence/
                service.py, api/graph_intelligence.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from forge.domain.graph.entities import GraphNode, GraphRelationship, GraphRelationshipKind


class DependencyDirection(StrEnum):
    """Which way to traverse from a node — defined once, applied uniformly
    across every relationship kind, all of which already point "source
    depends on target" (IMPORTS: importer->imported; CALLS: caller->callee;
    INHERITS: subclass->superclass — see domain/graph/entities.py::
    GraphRelationshipKind).

    UPSTREAM: things that depend on this node — reached via INCOMING edges
        (dependents/callers/importers/subclasses of this node).
    DOWNSTREAM: things this node depends on — reached via OUTGOING edges
        (this node's own dependencies).
    """

    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"


# Which of Phase 5's raw "incoming"/"outgoing" neighbor-direction strings
# corresponds to each `DependencyDirection` — the one place this mapping is
# defined, reused by application/graph_intelligence/service.py so it's never
# duplicated inline. Precisely typed (not `dict[..., str]`) so it slots
# directly into `GraphRepository.get_neighbors`'s `Literal["incoming",
# "outgoing", "both"]` parameter with no cast/ignore needed.
DIRECTION_TO_NEIGHBOR_DIRECTION: dict[DependencyDirection, Literal["incoming", "outgoing"]] = {
    DependencyDirection.UPSTREAM: "incoming",
    DependencyDirection.DOWNSTREAM: "outgoing",
}


@dataclass(frozen=True, slots=True)
class ImpactedNode:
    """One node reachable, transitively, from an impact-analysis starting
    node.

    Attributes:
        node: The impacted node.
        depth: The minimum number of hops from the starting node to reach
            this node — 1 for a direct dependency/dependent, 2 for one
            intermediate hop, etc. If a node is reachable via more than one
            path, this is the shortest of them (see
            infrastructure/graph_intelligence/neo4j_graph_intelligence_repository.py).
        relationship_kind: The kind of the relationship on the final
            (nearest) hop that reached this node at its minimum depth — a
            representative value, not an exhaustive multi-path report (see
            docs/architecture/06-code-intelligence.md, "Impact analysis").
    """

    node: GraphNode
    depth: int
    relationship_kind: GraphRelationshipKind


@dataclass(frozen=True, slots=True)
class ImpactAnalysisResult:
    """The complete outcome of one impact-analysis query.

    Attributes:
        starting_node_id: The node whose change is being analyzed.
        direction: UPSTREAM (default — "what could be affected if this
            changes") or DOWNSTREAM ("what this relies on").
        max_depth: The traversal bound that was applied.
        impacted_nodes: Every reachable node within `max_depth`, ordered by
            `depth` then `node.id` — never includes `starting_node_id`
            itself, even if a cycle would otherwise route back to it.
    """

    starting_node_id: UUID
    direction: DependencyDirection
    max_depth: int
    impacted_nodes: tuple[ImpactedNode, ...]


@dataclass(frozen=True, slots=True)
class DependencyPathResult:
    """The outcome of a dependency-path query between two nodes.

    Attributes:
        source_id: The path's starting node.
        target_id: The path's ending node.
        found: Whether a directed path exists within the requested
            `max_depth`. `False` is a normal, expected outcome — not an
            error (see docs/architecture/06-code-intelligence.md, "Path
            semantics").
        nodes: Ordered source-to-target, inclusive of both endpoints. Empty
            if `found` is `False`.
        relationships: Ordered source-to-target; `len(relationships) ==
            len(nodes) - 1`. Empty if `found` is `False`.
        length: Number of hops (`len(relationships)`); `0` for a
            `source_id == target_id` request; `None` if `found` is `False`.
    """

    source_id: UUID
    target_id: UUID
    found: bool
    nodes: tuple[GraphNode, ...]
    relationships: tuple[GraphRelationship, ...]
    length: int | None


@dataclass(frozen=True, slots=True)
class RelationshipKindCount:
    """How many relationships of one kind exist in a repository's graph."""

    kind: GraphRelationshipKind
    count: int


@dataclass(frozen=True, slots=True)
class NodeDegree:
    """One node's degree (edge count) for some ranking — the specific
    relationship kinds counted and whether it's in-, out-, or total degree
    depends on which list of a `GraphStatistics`/`GraphInsights` result this
    entry appears in (documented per-field there)."""

    node: GraphNode
    degree: int


@dataclass(frozen=True, slots=True)
class GraphStatistics:
    """A deterministic snapshot of one repository's projected graph.

    Attributes:
        repository_id: The repository this snapshot describes.
        total_nodes: Every node, any kind.
        total_files: `:File` nodes only.
        total_symbols: `:Symbol` nodes only.
        total_relationships: Every relationship, any kind.
        relationships_by_kind: One entry per `GraphRelationshipKind` —
            always all 5, zero-filled for kinds with no relationships, never
            silently omitted.
        highest_in_degree: Top-N nodes by in-degree, computed over ALL
            relationship kinds combined (a general "most central" signal —
            see `GraphInsights` for kind-scoped rankings). Ties broken by
            `node.id` for deterministic ordering.
        highest_out_degree: Top-N nodes by out-degree, same rules.
        projected_at: When this repository's graph was last projected, or
            `None` if it never has been.
        freshness: `"fresh"` (projected after the last parse),
            `"stale"` (parsed again since the last projection), or
            `"not_projected"` (`projected_at` is `None`). See
            docs/architecture/06-code-intelligence.md, "Graph freshness" —
            this only detects staleness from a re-parse, not a
            re-analysis-without-re-parse (a disclosed, not hidden, gap).
        computed_at: When this statistics snapshot itself was computed (UTC)
            — always "now", since nothing is cached.
    """

    repository_id: UUID
    total_nodes: int
    total_files: int
    total_symbols: int
    total_relationships: int
    relationships_by_kind: tuple[RelationshipKindCount, ...]
    highest_in_degree: tuple[NodeDegree, ...]
    highest_out_degree: tuple[NodeDegree, ...]
    projected_at: datetime | None
    freshness: str
    computed_at: datetime


@dataclass(frozen=True, slots=True)
class MutualImportPair:
    """Two files that directly import each other — the narrow,
    single-hop circular-dependency indicator (see
    docs/architecture/06-code-intelligence.md, "Insights" — this is
    deliberately not general cycle detection)."""

    file_a: GraphNode
    file_b: GraphNode


@dataclass(frozen=True, slots=True)
class GraphInsights:
    """Narrow, explainable structural signals about one repository's graph —
    never a scored/weighted recommendation, always a plain, reproducible
    graph fact (see docs/architecture/06-code-intelligence.md, "Insights").

    Attributes:
        repository_id: The repository these insights describe.
        most_connected_files: Top-N files by IMPORTS-only degree (in+out).
        dependency_hotspots: Top-N symbols by CALLS+INHERITS-only degree (in+out).
        isolated_nodes: Files with zero IMPORTS-degree, and symbols with
            zero CALLS+INHERITS-degree — the always-present structural
            CONTAINS/DEFINES relationships are deliberately excluded from
            this check (every file/symbol has one; counting them would make
            "isolated" meaningless).
        mutual_import_pairs: Direct A<->B IMPORTS pairs only — not general
            cycle detection (see `MutualImportPair`).
        unresolved_dependency_count: Read directly from Phase 4's PostgreSQL
            data (`DependencyEdge.resolution_status == UNRESOLVED`), never
            recomputed — Neo4j deliberately never projects unresolved edges
            (Phase 5's own design), so this is the one field here that
            doesn't come from a Neo4j query at all.
        computed_at: When this insights snapshot was computed (UTC).
    """

    repository_id: UUID
    most_connected_files: tuple[NodeDegree, ...]
    dependency_hotspots: tuple[NodeDegree, ...]
    isolated_nodes: tuple[GraphNode, ...]
    mutual_import_pairs: tuple[MutualImportPair, ...]
    unresolved_dependency_count: int
    computed_at: datetime
