"""Graph projection/query application service.

Purpose:       Orchestrate projecting an already-analyzed repository's
                PostgreSQL data into Neo4j, and querying the projected graph
                back.
Responsibility: Sequencing only. Reuses Phase 3's `ParsedFileRepository` and
                Phase 4's `DependencyEdgeRepository` to load already-persisted
                data — no filesystem access, no tree-sitter, no dependency
                resolution happens here, and no new Postgres reads beyond what
                those two ports already expose (`get_files`, `get_edges`).
                Mapping Postgres rows to graph entities is delegated to
                `infrastructure/graph/graph_mapping.py` (pure computation);
                writing/querying Neo4j is delegated to the injected
                `GraphRepository` (domain/graph/ports.py) — this class never
                imports the `neo4j` driver or constructs Cypher itself.
Depends on:    domain/graph/{entities,ports}.py, domain/parsing/ports.py,
                domain/dependency_analysis/ports.py, domain/repository/ports.py,
                domain/errors.py, infrastructure/graph/graph_mapping.py.
Depended on by: api/graph.py.
"""

from __future__ import annotations

from uuid import UUID

from forge.domain.dependency_analysis.entities import DependencyEdge
from forge.domain.dependency_analysis.ports import DependencyEdgeRepository
from forge.domain.errors import (
    GraphUnavailableError,
    NotFoundError,
    UnsupportedRepositoryStateError,
)
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
from forge.domain.repository.entities import RepositoryStatus
from forge.domain.repository.ports import RepositoryRepository
from forge.infrastructure.graph.graph_mapping import map_repository_graph

# Internal pagination page size for draining `DependencyEdgeRepository.get_edges`
# (a paginated, HTTP-shaped port — see domain/dependency_analysis/ports.py) down
# to the full edge set a repository-wide projection needs. Not a port change:
# looping client-side over the existing paginated method, exactly the pattern
# any other consumer needing "all rows" would already have to use.
_EDGE_PAGE_SIZE = 500


class GraphService:
    def __init__(
        self,
        repositories: RepositoryRepository,
        parsed_files: ParsedFileRepository,
        dependency_edges: DependencyEdgeRepository,
        graph: GraphRepository,
    ) -> None:
        self._repositories = repositories
        self._parsed_files = parsed_files
        self._dependency_edges = dependency_edges
        self._graph = graph

    async def project_repository(self, repository_id: UUID) -> ProjectionResult:
        """Run a full graph projection/rebuild and return (and persist to
        Neo4j) the result.

        Raises:
            NotFoundError: `repository_id` doesn't exist.
            UnsupportedRepositoryStateError: the repository isn't `READY`, or
                is `READY` but has no parsed files yet (Phase 3's `/parse`
                hasn't run) — there is nothing to project.
            GraphUnavailableError: Neo4j isn't reachable — checked before any
                write is attempted, so a caller gets a clear failure rather
                than a raw driver exception or a partially-applied projection.
        """
        repository = await self._repositories.get_by_id(repository_id)
        if repository is None:
            raise NotFoundError(f"Repository {repository_id} not found")
        if repository.status is not RepositoryStatus.READY:
            raise UnsupportedRepositoryStateError(
                f"Repository {repository_id} is {repository.status.value!r}, not READY"
            )

        files = await self._parsed_files.get_files(repository_id)
        if not files:
            raise UnsupportedRepositoryStateError(
                f"Repository {repository_id} has not been parsed yet — run "
                "POST .../parse first"
            )

        if not await self._graph.is_available():
            raise GraphUnavailableError(
                "Neo4j is not reachable — cannot project the graph. Start it via "
                "`docker compose -f infra/docker/docker-compose.yml up -d neo4j`."
            )

        edges = await self._load_all_edges(repository_id)
        nodes, relationships = map_repository_graph(repository, files, edges)
        return await self._graph.project_repository(repository_id, nodes, relationships)

    async def get_nodes(
        self,
        repository_id: UUID,
        *,
        kind: GraphNodeKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GraphNode]:
        await self._require_repository(repository_id)
        return await self._graph.get_nodes(repository_id, kind=kind, limit=limit, offset=offset)

    async def get_relationships(
        self,
        repository_id: UUID,
        *,
        kind: GraphRelationshipKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GraphRelationship]:
        await self._require_repository(repository_id)
        return await self._graph.get_relationships(
            repository_id, kind=kind, limit=limit, offset=offset
        )

    async def get_neighbors(
        self,
        repository_id: UUID,
        node_id: UUID,
        *,
        direction: str = "both",
        limit: int = 100,
    ) -> list[GraphNeighbor]:
        """Raises `NotFoundError` if `node_id` doesn't exist, or exists but
        belongs to a different repository — the two are deliberately
        indistinguishable (see domain/graph/ports.py)."""
        await self._require_repository(repository_id)
        neighbors = await self._graph.get_neighbors(
            repository_id, node_id, direction=direction, limit=limit  # type: ignore[arg-type]
        )
        if neighbors is None:
            raise NotFoundError(f"Node {node_id} not found in repository {repository_id}")
        return neighbors

    async def _load_all_edges(self, repository_id: UUID) -> list[DependencyEdge]:
        edges: list[DependencyEdge] = []
        offset = 0
        while True:
            page = await self._dependency_edges.get_edges(
                repository_id, limit=_EDGE_PAGE_SIZE, offset=offset
            )
            edges.extend(page)
            if len(page) < _EDGE_PAGE_SIZE:
                return edges
            offset += _EDGE_PAGE_SIZE

    async def _require_repository(self, repository_id: UUID) -> None:
        if await self._repositories.get_by_id(repository_id) is None:
            raise NotFoundError(f"Repository {repository_id} not found")
