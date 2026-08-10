"""Code-intelligence API router.

Purpose:       Expose deterministic graph-based code intelligence — direct
                dependencies/dependents, impact analysis, dependency paths,
                statistics, insights — over HTTP.
Responsibility: Translate between HTTP and
                application/graph_intelligence/service.py only — no
                resolution/traversal/Cypher logic here, matching
                api/graph.py's rule for its own router. `depth`/`limit`
                query params get their floor from FastAPI's own
                `Query(ge=...)` validation (422 on violation) and their
                ceiling from `Settings.graph_max_*` (checked in the handler
                body against the *injected* Settings, since a `Query(le=...)`
                bound is evaluated once at import time and can't read a
                per-request dependency) — a violation raises the existing
                `ValidationError` (400), no new error type. There is no
                endpoint that accepts client-supplied Cypher.
Depends on:    application/graph_intelligence/service.py,
                infrastructure/graph_intelligence/dependencies.py,
                infrastructure/graph/dependencies.py,
                infrastructure/persistence/dependencies.py, api/schemas.py,
                core/config.py.
Depended on by: core/app_factory.py (registers this router).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from forge.api.graph import to_relationship_response
from forge.api.schemas import (
    DependencyPathResponse,
    GraphInsightsResponse,
    GraphNeighborResponse,
    GraphNodeResponse,
    GraphStatisticsResponse,
    ImpactAnalysisResponse,
    ImpactedNodeResponse,
    MutualImportPairResponse,
    NodeDegreeResponse,
    RelationshipKindCountResponse,
)
from forge.application.graph_intelligence.service import GraphIntelligenceService
from forge.core.config import Settings, get_settings
from forge.domain.dependency_analysis.ports import DependencyEdgeRepository
from forge.domain.errors import ValidationError
from forge.domain.graph.entities import GraphNeighbor, GraphNode, GraphRelationshipKind
from forge.domain.graph.ports import GraphRepository
from forge.domain.graph_intelligence.entities import (
    DependencyDirection,
    DependencyPathResult,
    GraphInsights,
    GraphStatistics,
    ImpactAnalysisResult,
    ImpactedNode,
    MutualImportPair,
    NodeDegree,
)
from forge.domain.graph_intelligence.ports import GraphIntelligenceRepository
from forge.domain.parsing.ports import ParsedFileRepository
from forge.domain.repository.ports import RepositoryRepository
from forge.infrastructure.graph.dependencies import get_graph_repository
from forge.infrastructure.graph_intelligence.dependencies import get_graph_intelligence_repository
from forge.infrastructure.persistence.dependencies import (
    get_dependency_edge_repository,
    get_parsed_file_repository,
    get_repository_repository,
)

router = APIRouter(
    prefix="/projects/{project_id}/repositories/{repository_id}", tags=["graph-intelligence"]
)


def get_graph_intelligence_service(
    repositories: RepositoryRepository = Depends(get_repository_repository),
    graph: GraphRepository = Depends(get_graph_repository),
    intelligence: GraphIntelligenceRepository = Depends(get_graph_intelligence_repository),
    parsed_files: ParsedFileRepository = Depends(get_parsed_file_repository),
    dependency_edges: DependencyEdgeRepository = Depends(get_dependency_edge_repository),
) -> GraphIntelligenceService:
    return GraphIntelligenceService(
        repositories=repositories,
        graph=graph,
        intelligence=intelligence,
        parsed_files=parsed_files,
        dependency_edges=dependency_edges,
    )


@router.get("/graph/nodes/{node_id}/dependencies", response_model=list[GraphNeighborResponse])
async def list_dependencies(
    project_id: UUID,
    repository_id: UUID,
    node_id: UUID,
    kind: GraphRelationshipKind | None = None,
    limit: int = Query(100, ge=1),
    settings: Settings = Depends(get_settings),
    service: GraphIntelligenceService = Depends(get_graph_intelligence_service),
) -> list[GraphNeighborResponse]:
    """What `node_id` depends on (DOWNSTREAM). 404 if `node_id` doesn't exist
    within this repository — including when it belongs to a different one."""
    _check_limit(limit, settings)
    neighbors = await service.get_dependencies(repository_id, node_id, kind=kind, limit=limit)
    return [_to_neighbor_response(n) for n in neighbors]


@router.get("/graph/nodes/{node_id}/dependents", response_model=list[GraphNeighborResponse])
async def list_dependents(
    project_id: UUID,
    repository_id: UUID,
    node_id: UUID,
    kind: GraphRelationshipKind | None = None,
    limit: int = Query(100, ge=1),
    settings: Settings = Depends(get_settings),
    service: GraphIntelligenceService = Depends(get_graph_intelligence_service),
) -> list[GraphNeighborResponse]:
    """What depends on `node_id` (UPSTREAM). 404 if `node_id` doesn't exist
    within this repository."""
    _check_limit(limit, settings)
    neighbors = await service.get_dependents(repository_id, node_id, kind=kind, limit=limit)
    return [_to_neighbor_response(n) for n in neighbors]


@router.get("/graph/nodes/{node_id}/impact", response_model=ImpactAnalysisResponse)
async def get_impact(
    project_id: UUID,
    repository_id: UUID,
    node_id: UUID,
    direction: DependencyDirection = DependencyDirection.UPSTREAM,
    depth: int = Query(3, ge=1),
    kind: GraphRelationshipKind | None = None,
    limit: int = Query(100, ge=1),
    settings: Settings = Depends(get_settings),
    service: GraphIntelligenceService = Depends(get_graph_intelligence_service),
) -> ImpactAnalysisResponse:
    """Static dependency impact analysis: what could be affected if
    `node_id` changes (UPSTREAM, the default) or what it transitively relies
    on (DOWNSTREAM). See docs/architecture/06-code-intelligence.md, "Impact
    analysis" — this is static analysis only, not a runtime-behavior
    prediction. 404 if `node_id` doesn't exist within this repository."""
    _check_depth(depth, settings.graph_max_impact_depth, settings)
    _check_limit(limit, settings)
    result = await service.get_impact(
        repository_id, node_id, direction=direction, max_depth=depth, kind=kind, limit=limit
    )
    return _to_impact_response(result)


@router.get("/graph/path", response_model=DependencyPathResponse)
async def get_path(
    project_id: UUID,
    repository_id: UUID,
    source_id: UUID,
    target_id: UUID,
    depth: int = Query(6, ge=1),
    kind: GraphRelationshipKind | None = None,
    settings: Settings = Depends(get_settings),
    service: GraphIntelligenceService = Depends(get_graph_intelligence_service),
) -> DependencyPathResponse:
    """The shortest directed dependency path from `source_id` to
    `target_id`. `found=False` (200) is a normal result when both nodes
    exist but no path connects them within `depth` — 404 is reserved for
    `source_id`/`target_id` not existing within this repository (see
    docs/architecture/06-code-intelligence.md, "Path semantics")."""
    _check_depth(depth, settings.graph_max_path_depth, settings)
    result = await service.get_path(repository_id, source_id, target_id, max_depth=depth, kind=kind)
    return _to_path_response(result)


@router.get("/graph/statistics", response_model=GraphStatisticsResponse)
async def get_statistics(
    project_id: UUID,
    repository_id: UUID,
    limit: int = Query(10, ge=1),
    settings: Settings = Depends(get_settings),
    service: GraphIntelligenceService = Depends(get_graph_intelligence_service),
) -> GraphStatisticsResponse:
    """A deterministic snapshot of this repository's projected graph,
    including `freshness` (`"fresh"`/`"stale"`/`"not_projected"`) — see
    docs/architecture/06-code-intelligence.md, "Graph freshness". Never an
    error for an unprojected repository — every count is simply `0`."""
    _check_limit(limit, settings)
    statistics = await service.get_statistics(repository_id, limit=limit)
    return _to_statistics_response(statistics)


@router.get("/graph/insights", response_model=GraphInsightsResponse)
async def get_insights(
    project_id: UUID,
    repository_id: UUID,
    limit: int = Query(20, ge=1),
    settings: Settings = Depends(get_settings),
    service: GraphIntelligenceService = Depends(get_graph_intelligence_service),
) -> GraphInsightsResponse:
    """Narrow, explainable structural insights — never an AI recommendation,
    always a plain, reproducible graph fact or count (see
    docs/architecture/06-code-intelligence.md, "Insights")."""
    _check_limit(limit, settings)
    insights = await service.get_insights(repository_id, limit=limit)
    return _to_insights_response(insights)


def _check_limit(limit: int, settings: Settings) -> None:
    if limit > settings.graph_max_result_limit:
        raise ValidationError(
            f"limit {limit} exceeds the maximum of {settings.graph_max_result_limit}"
        )


def _check_depth(depth: int, max_depth: int, settings: Settings) -> None:
    if depth > max_depth:
        raise ValidationError(f"depth {depth} exceeds the maximum of {max_depth}")


def _to_node_response(node: GraphNode) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=node.id,
        kind=node.kind.value,
        repository_id=node.repository_id,
        properties=node.properties,
    )


def _to_neighbor_response(neighbor: GraphNeighbor) -> GraphNeighborResponse:
    return GraphNeighborResponse(
        node=_to_node_response(neighbor.node),
        relationship_kind=neighbor.relationship_kind.value,
        direction=neighbor.direction,
    )


def _to_impacted_node_response(impacted: ImpactedNode) -> ImpactedNodeResponse:
    return ImpactedNodeResponse(
        node=_to_node_response(impacted.node),
        depth=impacted.depth,
        relationship_kind=impacted.relationship_kind.value,
    )


def _to_impact_response(result: ImpactAnalysisResult) -> ImpactAnalysisResponse:
    return ImpactAnalysisResponse(
        starting_node_id=result.starting_node_id,
        direction=result.direction.value,
        max_depth=result.max_depth,
        impacted_nodes=[_to_impacted_node_response(n) for n in result.impacted_nodes],
    )


def _to_path_response(result: DependencyPathResult) -> DependencyPathResponse:
    return DependencyPathResponse(
        source_id=result.source_id,
        target_id=result.target_id,
        found=result.found,
        nodes=[_to_node_response(n) for n in result.nodes],
        relationships=[to_relationship_response(r) for r in result.relationships],
        length=result.length,
    )


def _to_node_degree_response(entry: NodeDegree) -> NodeDegreeResponse:
    return NodeDegreeResponse(node=_to_node_response(entry.node), degree=entry.degree)


def _to_statistics_response(statistics: GraphStatistics) -> GraphStatisticsResponse:
    return GraphStatisticsResponse(
        repository_id=statistics.repository_id,
        total_nodes=statistics.total_nodes,
        total_files=statistics.total_files,
        total_symbols=statistics.total_symbols,
        total_relationships=statistics.total_relationships,
        relationships_by_kind=[
            RelationshipKindCountResponse(kind=entry.kind.value, count=entry.count)
            for entry in statistics.relationships_by_kind
        ],
        highest_in_degree=[_to_node_degree_response(e) for e in statistics.highest_in_degree],
        highest_out_degree=[_to_node_degree_response(e) for e in statistics.highest_out_degree],
        projected_at=statistics.projected_at,
        freshness=statistics.freshness,
        computed_at=statistics.computed_at,
    )


def _to_mutual_pair_response(pair: MutualImportPair) -> MutualImportPairResponse:
    return MutualImportPairResponse(
        file_a=_to_node_response(pair.file_a), file_b=_to_node_response(pair.file_b)
    )


def _to_insights_response(insights: GraphInsights) -> GraphInsightsResponse:
    return GraphInsightsResponse(
        repository_id=insights.repository_id,
        most_connected_files=[_to_node_degree_response(e) for e in insights.most_connected_files],
        dependency_hotspots=[_to_node_degree_response(e) for e in insights.dependency_hotspots],
        isolated_nodes=[_to_node_response(n) for n in insights.isolated_nodes],
        mutual_import_pairs=[_to_mutual_pair_response(p) for p in insights.mutual_import_pairs],
        unresolved_dependency_count=insights.unresolved_dependency_count,
        computed_at=insights.computed_at,
    )
