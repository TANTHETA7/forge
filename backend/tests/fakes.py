"""In-memory fakes for the Phase 2/3/4/5 persistence ports.

Purpose: Let unit/integration tests exercise application services and API routes
against real port contracts (`ProjectRepository`, `RepositoryRepository`,
`ParsedFileRepository`, `DependencyEdgeRepository`, `GraphRepository`) without
a live Postgres/Neo4j — real-backend coverage for the concrete implementations
lives in tests/integration/test_postgres_persistence.py,
test_postgres_parsing_persistence.py, test_postgres_dependency_persistence.py,
and test_neo4j_graph_projection.py instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from forge.domain.dependency_analysis.entities import (
    DependencyEdge,
    DependencyKind,
    ResolutionStatus,
)
from forge.domain.graph.entities import (
    GraphNeighbor,
    GraphNode,
    GraphNodeKind,
    GraphRelationship,
    GraphRelationshipKind,
    ProjectionResult,
)
from forge.domain.parsing.entities import ParsedFile, ParseError, ParseResult, Symbol, SymbolKind
from forge.domain.project.entities import Project
from forge.domain.repository.entities import Repository


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[UUID, Project] = {}

    async def create(self, project: Project) -> None:
        self._projects[project.id] = project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return self._projects.get(project_id)

    async def update(self, project: Project) -> None:
        self._projects[project.id] = project


class InMemoryRepositoryRepository:
    def __init__(self) -> None:
        self._repositories: dict[UUID, Repository] = {}

    async def create(self, repository: Repository) -> None:
        self._repositories[repository.id] = repository

    async def get_by_id(self, repository_id: UUID) -> Repository | None:
        return self._repositories.get(repository_id)

    async def update(self, repository: Repository) -> None:
        self._repositories[repository.id] = repository


class InMemoryParsedFileRepository:
    """Mirrors `SqlAlchemyParsedFileRepository`'s replace-on-reparse semantics —
    `save_parse_result` discards any previous result for the same repository."""

    def __init__(self) -> None:
        self._results: dict[UUID, ParseResult] = {}

    async def save_parse_result(self, result: ParseResult) -> None:
        self._results[result.repository_id] = result

    async def get_files(self, repository_id: UUID) -> list[ParsedFile]:
        result = self._results.get(repository_id)
        return list(result.files) if result else []

    async def get_symbols(
        self,
        repository_id: UUID,
        *,
        kind: SymbolKind | None = None,
        file_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Symbol]:
        result = self._results.get(repository_id)
        if result is None:
            return []
        symbols = [
            symbol
            for file in result.files
            if file_id is None or file.id == file_id
            for symbol in file.symbols
            if kind is None or symbol.kind is kind
        ]
        return symbols[offset : offset + limit]

    async def get_symbol(self, symbol_id: UUID) -> Symbol | None:
        for result in self._results.values():
            for file in result.files:
                for symbol in file.symbols:
                    if symbol.id == symbol_id:
                        return symbol
        return None

    async def get_errors(self, repository_id: UUID) -> list[ParseError]:
        result = self._results.get(repository_id)
        return list(result.errors) if result else []


class InMemoryDependencyEdgeRepository:
    """Mirrors `SqlAlchemyDependencyEdgeRepository`'s replace-on-reanalysis
    semantics — `save_analysis_result` discards any previous edges for the
    same repository."""

    def __init__(self) -> None:
        self._edges: dict[UUID, tuple[DependencyEdge, ...]] = {}

    async def save_analysis_result(
        self, repository_id: UUID, edges: tuple[DependencyEdge, ...]
    ) -> None:
        self._edges[repository_id] = edges

    async def get_edges(
        self,
        repository_id: UUID,
        *,
        kind: DependencyKind | None = None,
        source_symbol_id: UUID | None = None,
        target_symbol_id: UUID | None = None,
        resolution_status: ResolutionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DependencyEdge]:
        edges = [
            edge
            for edge in self._edges.get(repository_id, ())
            if (kind is None or edge.kind is kind)
            and (source_symbol_id is None or edge.source_symbol_id == source_symbol_id)
            and (target_symbol_id is None or edge.target_symbol_id == target_symbol_id)
            and (resolution_status is None or edge.resolution_status is resolution_status)
        ]
        return edges[offset : offset + limit]

    async def get_edge(self, dependency_id: UUID) -> DependencyEdge | None:
        for edges in self._edges.values():
            for edge in edges:
                if edge.id == dependency_id:
                    return edge
        return None


class InMemoryGraphRepository:
    """Mirrors `Neo4jGraphRepository`'s replace-on-reproject semantics —
    `project_repository` discards any previous graph for the same
    repository. `available` is a plain public attribute a test can flip to
    simulate Neo4j being unreachable."""

    def __init__(self, *, available: bool = True) -> None:
        self._nodes: dict[UUID, tuple[GraphNode, ...]] = {}
        self._relationships: dict[UUID, tuple[GraphRelationship, ...]] = {}
        self.available = available

    async def project_repository(
        self,
        repository_id: UUID,
        nodes: tuple[GraphNode, ...],
        relationships: tuple[GraphRelationship, ...],
    ) -> ProjectionResult:
        self._nodes[repository_id] = nodes
        self._relationships[repository_id] = relationships
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
        nodes = [n for n in self._nodes.get(repository_id, ()) if kind is None or n.kind is kind]
        return nodes[offset : offset + limit]

    async def get_relationships(
        self,
        repository_id: UUID,
        *,
        kind: GraphRelationshipKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GraphRelationship]:
        relationships = [
            r for r in self._relationships.get(repository_id, ()) if kind is None or r.kind is kind
        ]
        return relationships[offset : offset + limit]

    async def get_neighbors(
        self,
        repository_id: UUID,
        node_id: UUID,
        *,
        direction: Literal["incoming", "outgoing", "both"] = "both",
        limit: int = 100,
    ) -> list[GraphNeighbor] | None:
        nodes_by_id = {node.id: node for node in self._nodes.get(repository_id, ())}
        if node_id not in nodes_by_id:
            return None

        neighbors: list[GraphNeighbor] = []
        for relationship in self._relationships.get(repository_id, ()):
            if relationship.source_id == node_id and direction in ("outgoing", "both"):
                target = nodes_by_id.get(relationship.target_id)
                if target is not None:
                    neighbors.append(
                        GraphNeighbor(
                            node=target, relationship_kind=relationship.kind, direction="outgoing"
                        )
                    )
            if relationship.target_id == node_id and direction in ("incoming", "both"):
                source = nodes_by_id.get(relationship.source_id)
                if source is not None:
                    neighbors.append(
                        GraphNeighbor(
                            node=source, relationship_kind=relationship.kind, direction="incoming"
                        )
                    )
        return neighbors[:limit]

    async def is_available(self) -> bool:
        return self.available
