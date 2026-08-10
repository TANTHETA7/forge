"""Graph projection/query API router.

Purpose:       Expose Neo4j graph projection (trigger) and queries (read) over
                HTTP.
Responsibility: Translate between HTTP and application/graph/service.py
                only — no resolution, mapping, or Cypher lives here, matching
                api/dependencies.py's rule for its own router. Every read
                route maps to a fixed, structured response shape — never raw
                Cypher output, and there is no endpoint that accepts
                client-supplied Cypher (see docs/architecture/05-knowledge-graph.md,
                "Security").
Depends on:    application/graph/service.py, infrastructure/graph/dependencies.py,
                infrastructure/persistence/dependencies.py, api/schemas.py.
Depended on by: core/app_factory.py (registers this router).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status

from forge.api.schemas import (
    GraphNeighborResponse,
    GraphNodeResponse,
    GraphRelationshipResponse,
    ProjectionSummaryResponse,
)
from forge.application.graph.service import GraphService
from forge.domain.dependency_analysis.ports import DependencyEdgeRepository
from forge.domain.graph.entities import (
    GraphNeighbor,
    GraphNode,
    GraphNodeKind,
    GraphRelationship,
    GraphRelationshipKind,
    ProjectionResult,
)
from forge.domain.graph.ports import GraphRepository
from forge.domain.parsing.ports import ParsedFileRepository
from forge.domain.repository.ports import RepositoryRepository
from forge.infrastructure.graph.dependencies import get_graph_repository
from forge.infrastructure.persistence.dependencies import (
    get_dependency_edge_repository,
    get_parsed_file_repository,
    get_repository_repository,
)

router = APIRouter(
    prefix="/projects/{project_id}/repositories/{repository_id}", tags=["graph"]
)


def get_graph_service(
    repositories: RepositoryRepository = Depends(get_repository_repository),
    parsed_files: ParsedFileRepository = Depends(get_parsed_file_repository),
    dependency_edges: DependencyEdgeRepository = Depends(get_dependency_edge_repository),
    graph: GraphRepository = Depends(get_graph_repository),
) -> GraphService:
    return GraphService(
        repositories=repositories,
        parsed_files=parsed_files,
        dependency_edges=dependency_edges,
        graph=graph,
    )


@router.post(
    "/graph/project",
    response_model=ProjectionSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def project_graph(
    project_id: UUID,
    repository_id: UUID,
    service: GraphService = Depends(get_graph_service),
) -> ProjectionSummaryResponse:
    """Run a full graph projection/rebuild for an already-parsed `READY`
    repository.

    404s if the repository doesn't exist; 409s if it exists but isn't
    `READY`, or is `READY` but hasn't been parsed yet; 503 if Neo4j isn't
    reachable (all via api/error_handlers.py). Idempotent — re-running
    replaces any previous projection for this repository with current
    PostgreSQL state.
    """
    result = await service.project_repository(repository_id)
    return _to_summary(result)


@router.get("/graph/nodes", response_model=list[GraphNodeResponse])
async def list_graph_nodes(
    project_id: UUID,
    repository_id: UUID,
    kind: GraphNodeKind | None = None,
    limit: int = 100,
    offset: int = 0,
    service: GraphService = Depends(get_graph_service),
) -> list[GraphNodeResponse]:
    """Graph nodes for this repository, optionally filtered by `kind`,
    paginated. Only requires the repository to exist — an empty list if
    nothing has been projected yet, not an error."""
    nodes = await service.get_nodes(repository_id, kind=kind, limit=limit, offset=offset)
    return [_to_node_response(node) for node in nodes]


@router.get("/graph/dependencies", response_model=list[GraphRelationshipResponse])
async def list_graph_dependencies(
    project_id: UUID,
    repository_id: UUID,
    kind: GraphRelationshipKind | None = None,
    limit: int = 100,
    offset: int = 0,
    service: GraphService = Depends(get_graph_service),
) -> list[GraphRelationshipResponse]:
    """IMPORTS/CALLS/INHERITS (and structural CONTAINS/DEFINES) relationships
    for this repository, optionally filtered by `kind`, paginated — a
    structured, typed list, never raw Cypher output."""
    relationships = await service.get_relationships(
        repository_id, kind=kind, limit=limit, offset=offset
    )
    return [to_relationship_response(r) for r in relationships]


@router.get("/graph/neighbors/{node_id}", response_model=list[GraphNeighborResponse])
async def list_graph_neighbors(
    project_id: UUID,
    repository_id: UUID,
    node_id: UUID,
    direction: Literal["incoming", "outgoing", "both"] = "both",
    limit: int = 100,
    service: GraphService = Depends(get_graph_service),
) -> list[GraphNeighborResponse]:
    """A node's direct neighbors. 404 if `node_id` doesn't exist within this
    repository — including when it exists but belongs to a *different*
    repository, which is deliberately indistinguishable from not existing at
    all (see docs/architecture/05-knowledge-graph.md, "Security")."""
    neighbors = await service.get_neighbors(
        repository_id, node_id, direction=direction, limit=limit
    )
    return [_to_neighbor_response(n) for n in neighbors]


def _to_summary(result: ProjectionResult) -> ProjectionSummaryResponse:
    return ProjectionSummaryResponse(
        repository_id=result.repository_id,
        node_count=result.node_count,
        relationship_count=result.relationship_count,
        projected_at=result.projected_at,
    )


def _to_node_response(node: GraphNode) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=node.id,
        kind=node.kind.value,
        repository_id=node.repository_id,
        properties=node.properties,
    )


def to_relationship_response(relationship: GraphRelationship) -> GraphRelationshipResponse:
    """Module-level (not private) so api/graph_intelligence.py (Phase 6) can
    reuse it for `DependencyPathResponse.relationships` rather than
    duplicating the same `GraphRelationship`->`GraphRelationshipResponse`
    mapping."""
    return GraphRelationshipResponse(
        source_id=relationship.source_id,
        target_id=relationship.target_id,
        kind=relationship.kind.value,
        repository_id=relationship.repository_id,
        dependency_edge_id=relationship.dependency_edge_id,
        properties=relationship.properties,
    )


def _to_neighbor_response(neighbor: GraphNeighbor) -> GraphNeighborResponse:
    return GraphNeighborResponse(
        node=_to_node_response(neighbor.node),
        relationship_kind=neighbor.relationship_kind.value,
        direction=neighbor.direction,
    )
