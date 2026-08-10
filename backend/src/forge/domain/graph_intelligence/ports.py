"""Ports the code-intelligence workflow depends on, implemented by
infrastructure and injected into `application/graph_intelligence/service.py`.

Purpose:       Let the application layer run impact analysis, dependency-path
                queries, statistics, and insights without importing the
                `neo4j` driver or Cypher directly — the same rule every
                earlier phase already established.
Responsibility: One interface, `GraphIntelligenceRepository` — impact/path/
                statistics/insights only. Direct dependency/dependent
                exploration (Capability 1) deliberately has NO method here:
                it's built entirely on top of the existing, unmodified-in-
                shape `domain/graph/ports.py::GraphRepository.get_neighbors`
                (extended in Phase 6 with an optional `kind` filter) by
                `GraphIntelligenceService` itself — adding a second port
                method for the exact same single-hop traversal would only
                duplicate `infrastructure/graph/neo4j_graph_repository.py`'s
                existing `_get_neighbors_tx` (see
                docs/architecture/06-code-intelligence.md, "Graph query port
                design").
Depends on:    domain/graph_intelligence/entities.py, domain/graph/entities.py.
Depended on by: application/graph_intelligence/service.py; implemented by
                infrastructure/graph_intelligence/neo4j_graph_intelligence_repository.py.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from forge.domain.graph.entities import GraphRelationshipKind
from forge.domain.graph_intelligence.entities import (
    DependencyDirection,
    DependencyPathResult,
    GraphInsights,
    GraphStatistics,
    ImpactAnalysisResult,
)


class GraphIntelligenceRepository(Protocol):
    """Read-only query port over a repository's Neo4j graph projection for
    multi-hop/aggregate questions — never a write path (projection stays
    exclusively `domain/graph/ports.py::GraphRepository`'s responsibility).
    Every method is scoped to one `repository_id`, sourced only from
    server-side/path data — the same repository-isolation-by-construction
    rule `GraphRepository` already established.
    """

    async def get_impact(
        self,
        repository_id: UUID,
        node_id: UUID,
        *,
        direction: DependencyDirection = DependencyDirection.UPSTREAM,
        max_depth: int,
        kind: GraphRelationshipKind | None = None,
        limit: int,
    ) -> ImpactAnalysisResult | None:
        """Bounded transitive-dependency traversal from `node_id`. `None` if
        `node_id` doesn't exist within this repository. Never raises for a
        node with zero impacted nodes — an empty `impacted_nodes` tuple is a
        normal result."""
        ...

    async def get_path(
        self,
        repository_id: UUID,
        source_id: UUID,
        target_id: UUID,
        *,
        max_depth: int,
        kind: GraphRelationshipKind | None = None,
    ) -> DependencyPathResult | None:
        """Directed shortest path from `source_id` to `target_id`. `None` if
        either node doesn't exist within this repository — distinct from a
        `DependencyPathResult` with `found=False` (both nodes exist, no path
        connects them within `max_depth`)."""
        ...

    async def get_statistics(self, repository_id: UUID, *, limit: int) -> GraphStatistics:
        """A deterministic snapshot of this repository's graph — `limit`
        bounds `highest_in_degree`/`highest_out_degree`. Never raises for an
        unprojected repository — every count is simply `0`. `freshness` here
        only reflects whether `projected_at` is set (`"not_projected"` vs. a
        placeholder for "projected") — the real `"fresh"`/`"stale"`
        comparison against PostgreSQL happens in
        `GraphIntelligenceService.get_statistics`, which is the only layer
        with access to both Neo4j and `ParsedFileRepository`."""
        ...

    async def get_insights(self, repository_id: UUID, *, limit: int) -> GraphInsights:
        """Structural insights for this repository's graph. `insights.
        unresolved_dependency_count` is populated by the caller (application
        layer), not this method — a Neo4j query has no access to Phase 4's
        PostgreSQL data (see `GraphIntelligenceService.get_insights`)."""
        ...
