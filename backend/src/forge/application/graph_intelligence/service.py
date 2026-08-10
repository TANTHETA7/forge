"""Code-intelligence application service.

Purpose:       Orchestrate deterministic graph-based queries over an
                already-projected repository's Neo4j graph — dependency
                exploration, impact analysis, dependency paths, statistics,
                and insights.
Responsibility: Sequencing and vocabulary translation only. Reuses Phase 5's
                `GraphRepository` for direct dependency/dependent exploration
                (Capability 1 — no new Cypher, see
                docs/architecture/06-code-intelligence.md) and the new
                `GraphIntelligenceRepository` for multi-hop/aggregate
                queries. Never imports the `neo4j` driver or constructs
                Cypher itself.

                This is also the ONLY layer with access to both Neo4j (via
                `GraphIntelligenceRepository`) and PostgreSQL (via
                `ParsedFileRepository`) — which is why graph-freshness
                classification (comparing the graph's `projected_at` against
                Postgres's `parsed_files.parsed_at`) happens here in
                `get_statistics`, not in `Neo4jGraphIntelligenceRepository`
                (which has no Postgres access at all) and not in Phase 3/5
                infrastructure (neither has any reason to know about the
                other).
Depends on:    domain/graph_intelligence/{entities,ports}.py,
                domain/graph/{entities,ports}.py, domain/parsing/ports.py,
                domain/dependency_analysis/ports.py, domain/repository/ports.py,
                domain/errors.py.
Depended on by: api/graph_intelligence.py.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from forge.domain.dependency_analysis.entities import ResolutionStatus
from forge.domain.dependency_analysis.ports import DependencyEdgeRepository
from forge.domain.errors import NotFoundError
from forge.domain.graph.entities import GraphNeighbor, GraphRelationshipKind
from forge.domain.graph.ports import GraphRepository
from forge.domain.graph_intelligence.entities import (
    DIRECTION_TO_NEIGHBOR_DIRECTION,
    DependencyDirection,
    DependencyPathResult,
    GraphInsights,
    GraphStatistics,
    ImpactAnalysisResult,
)
from forge.domain.graph_intelligence.ports import GraphIntelligenceRepository
from forge.domain.parsing.ports import ParsedFileRepository
from forge.domain.repository.ports import RepositoryRepository

# Internal pagination page size for counting unresolved DependencyEdges via
# the existing paginated `DependencyEdgeRepository.get_edges` — same pattern
# `application/graph/service.py::GraphService._load_all_edges` already
# established in Phase 5. Not a port change: looping client-side over the
# existing method, never touching Phase 4's dependency-resolution logic.
_EDGE_PAGE_SIZE = 500


class GraphIntelligenceService:
    def __init__(
        self,
        repositories: RepositoryRepository,
        graph: GraphRepository,
        intelligence: GraphIntelligenceRepository,
        parsed_files: ParsedFileRepository,
        dependency_edges: DependencyEdgeRepository,
    ) -> None:
        self._repositories = repositories
        self._graph = graph
        self._intelligence = intelligence
        self._parsed_files = parsed_files
        self._dependency_edges = dependency_edges

    async def get_dependencies(
        self,
        repository_id: UUID,
        node_id: UUID,
        *,
        kind: GraphRelationshipKind | None = None,
        limit: int = 100,
    ) -> list[GraphNeighbor]:
        """What `node_id` depends on — DOWNSTREAM traversal (§domain/
        graph_intelligence/entities.py::DependencyDirection). Raises
        `NotFoundError` if `node_id` doesn't exist within this repository."""
        return await self._get_neighbors(
            repository_id, node_id, DependencyDirection.DOWNSTREAM, kind, limit
        )

    async def get_dependents(
        self,
        repository_id: UUID,
        node_id: UUID,
        *,
        kind: GraphRelationshipKind | None = None,
        limit: int = 100,
    ) -> list[GraphNeighbor]:
        """What depends on `node_id` — UPSTREAM traversal. Raises
        `NotFoundError` if `node_id` doesn't exist within this repository."""
        return await self._get_neighbors(
            repository_id, node_id, DependencyDirection.UPSTREAM, kind, limit
        )

    async def get_impact(
        self,
        repository_id: UUID,
        node_id: UUID,
        *,
        direction: DependencyDirection = DependencyDirection.UPSTREAM,
        max_depth: int,
        kind: GraphRelationshipKind | None = None,
        limit: int,
    ) -> ImpactAnalysisResult:
        """Static dependency impact analysis: what could be affected if
        `node_id` changes (UPSTREAM, the default — the transitive closure of
        things that depend on it), or what `node_id` itself transitively
        relies on (DOWNSTREAM). Derived entirely from Phase 4's
        statically-resolved CALLS/IMPORTS/INHERITS edges — this does not
        model dynamic dispatch, runtime polymorphism, or reflection (see
        docs/architecture/06-code-intelligence.md, "Impact analysis"). Raises
        `NotFoundError` if `node_id` doesn't exist within this repository."""
        await self._require_repository(repository_id)
        result = await self._intelligence.get_impact(
            repository_id,
            node_id,
            direction=direction,
            max_depth=max_depth,
            kind=kind,
            limit=limit,
        )
        if result is None:
            raise NotFoundError(f"Node {node_id} not found in repository {repository_id}")
        return result

    async def get_path(
        self,
        repository_id: UUID,
        source_id: UUID,
        target_id: UUID,
        *,
        max_depth: int,
        kind: GraphRelationshipKind | None = None,
    ) -> DependencyPathResult:
        """The shortest directed dependency path from `source_id` to
        `target_id`, if one exists within `max_depth`. A `DependencyPathResult`
        with `found=False` is a normal, expected result — not an error (see
        docs/architecture/06-code-intelligence.md, "Path semantics"). Raises
        `NotFoundError` only if `source_id` or `target_id` itself doesn't
        exist within this repository."""
        await self._require_repository(repository_id)
        result = await self._intelligence.get_path(
            repository_id, source_id, target_id, max_depth=max_depth, kind=kind
        )
        if result is None:
            raise NotFoundError(
                f"Source {source_id} or target {target_id} not found in repository "
                f"{repository_id}"
            )
        return result

    async def get_statistics(self, repository_id: UUID, *, limit: int = 10) -> GraphStatistics:
        """A deterministic snapshot of this repository's projected graph,
        with `freshness` correctly classified against PostgreSQL (the only
        place that comparison can happen — see this module's own docstring):

        - `"not_projected"`: the graph has never been projected
          (`projected_at` is `None`).
        - `"stale"`: the repository has been re-parsed since the graph was
          last projected — `POST .../graph/project` should be re-run.
        - `"fresh"`: the graph reflects the repository's current parsed
          state.

        This only detects staleness from a re-*parse* — a re-*analysis*
        (Phase 4) with no re-parse in between is not detectable this way,
        since PostgreSQL stores no `analyzed_at` timestamp (see
        docs/architecture/06-code-intelligence.md, "Graph freshness", for
        why this is a disclosed, not hidden, limitation). Never raises for
        an unprojected or unanalyzed repository — every count is simply `0`."""
        await self._require_repository(repository_id)
        statistics = await self._intelligence.get_statistics(repository_id, limit=limit)
        last_parsed_at = await self._parsed_files.get_last_parsed_at(repository_id)

        if statistics.projected_at is None:
            freshness = "not_projected"
        elif last_parsed_at is not None and last_parsed_at > statistics.projected_at:
            freshness = "stale"
        else:
            freshness = "fresh"

        return replace(
            statistics, freshness=freshness, computed_at=datetime.now(UTC)
        )

    async def get_insights(self, repository_id: UUID, *, limit: int = 20) -> GraphInsights:
        """Narrow, explainable structural signals for this repository — never
        a scored/weighted recommendation, always a plain, reproducible graph
        fact or count (see docs/architecture/06-code-intelligence.md,
        "Insights"). `unresolved_dependency_count` is read directly from
        Phase 4's PostgreSQL data, not recomputed — Neo4j never projects
        AMBIGUOUS/UNRESOLVED edges at all (Phase 5's own design), so this is
        the one field here with no Neo4j equivalent to derive it from."""
        await self._require_repository(repository_id)
        insights = await self._intelligence.get_insights(repository_id, limit=limit)
        unresolved_count = await self._count_unresolved_edges(repository_id)
        return replace(
            insights, unresolved_dependency_count=unresolved_count, computed_at=datetime.now(UTC)
        )

    async def _count_unresolved_edges(self, repository_id: UUID) -> int:
        count = 0
        offset = 0
        while True:
            page = await self._dependency_edges.get_edges(
                repository_id,
                resolution_status=ResolutionStatus.UNRESOLVED,
                limit=_EDGE_PAGE_SIZE,
                offset=offset,
            )
            count += len(page)
            if len(page) < _EDGE_PAGE_SIZE:
                return count
            offset += _EDGE_PAGE_SIZE

    async def _get_neighbors(
        self,
        repository_id: UUID,
        node_id: UUID,
        direction: DependencyDirection,
        kind: GraphRelationshipKind | None,
        limit: int,
    ) -> list[GraphNeighbor]:
        await self._require_repository(repository_id)
        neighbors = await self._graph.get_neighbors(
            repository_id,
            node_id,
            direction=DIRECTION_TO_NEIGHBOR_DIRECTION[direction],
            kind=kind,
            limit=limit,
        )
        if neighbors is None:
            raise NotFoundError(f"Node {node_id} not found in repository {repository_id}")
        return neighbors

    async def _require_repository(self, repository_id: UUID) -> None:
        if await self._repositories.get_by_id(repository_id) is None:
            raise NotFoundError(f"Repository {repository_id} not found")
