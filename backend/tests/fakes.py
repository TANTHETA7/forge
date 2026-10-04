"""In-memory fakes for the Phase 2/3/4/5/6 persistence ports.

Purpose: Let unit/integration tests exercise application services and API routes
against real port contracts (`ProjectRepository`, `RepositoryRepository`,
`ParsedFileRepository`, `DependencyEdgeRepository`, `GraphRepository`,
`GraphIntelligenceRepository`) without a live Postgres/Neo4j — real-backend
coverage for the concrete implementations lives in
tests/integration/test_postgres_persistence.py,
test_postgres_parsing_persistence.py, test_postgres_dependency_persistence.py,
test_neo4j_graph_projection.py, and test_neo4j_graph_intelligence.py instead.

`InMemoryGraphIntelligenceRepository` deliberately wraps an
`InMemoryGraphRepository` instance rather than keeping its own separate node/
relationship store — mirroring how, in production, `Neo4jGraphIntelligenceRepository`
and `Neo4jGraphRepository` both read the exact same live Neo4j data, just
through different query strategies. Its `get_impact` is a genuine (if small)
breadth-first traversal — not a stub — matching Phase 4/5's own
`InMemoryDependencyEdgeRepository`/`InMemoryGraphRepository` precedent of
real reimplementations for API-layer wiring tests; semantic correctness at
scale is proven exclusively against real Neo4j (see
tests/integration/test_neo4j_graph_intelligence.py).
"""

from __future__ import annotations

import dataclasses
from collections import Counter, deque
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from forge.domain.dependency_analysis.entities import (
    DependencyEdge,
    DependencyKind,
    ResolutionStatus,
)
from forge.domain.errors import GraphUnavailableError, RagProviderError
from forge.domain.graph.entities import (
    GraphNeighbor,
    GraphNode,
    GraphNodeKind,
    GraphRelationship,
    GraphRelationshipKind,
    ProjectionResult,
)
from forge.domain.graph_intelligence.entities import (
    DependencyDirection,
    DependencyPathResult,
    GraphInsights,
    GraphStatistics,
    ImpactAnalysisResult,
    ImpactedNode,
    MutualImportPair,
    NodeDegree,
    RelationshipKindCount,
)
from forge.domain.parsing.entities import (
    ParsedFile,
    ParsedFileSummary,
    ParseError,
    ParseResult,
    Symbol,
    SymbolKind,
)
from forge.domain.project.entities import Project
from forge.domain.rag.entities import (
    ChunkEmbedding,
    CodeChunk,
    EmbeddedChunk,
    IndexStatus,
)
from forge.domain.rag.retrieval import extract_lexical_terms
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

    async def get_file_summaries(self, repository_id: UUID) -> list[ParsedFileSummary]:
        result = self._results.get(repository_id)
        if result is None:
            return []
        return [
            ParsedFileSummary(
                id=file.id,
                repository_id=file.repository_id,
                path=file.path,
                language=file.language,
                has_syntax_errors=file.has_syntax_errors,
                symbol_count=len(file.symbols),
                import_count=len(file.imports),
            )
            for file in sorted(result.files, key=lambda file: (file.path, str(file.id)))
        ]

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

    async def get_last_parsed_at(self, repository_id: UUID) -> datetime | None:
        result = self._results.get(repository_id)
        return result.parsed_at if result else None


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
        projected_at = datetime.now(UTC)
        # Mirrors Neo4jGraphRepository's own `_write_projected_at_tx` — stamp
        # the Repository node with when this projection ran, so a test
        # exercising GraphIntelligenceService.get_statistics's freshness
        # classification against this fake sees the same shape real Neo4j
        # produces (see infrastructure/graph/neo4j_graph_repository.py).
        stamped_nodes = tuple(
            dataclasses.replace(
                node, properties={**node.properties, "projected_at": projected_at.isoformat()}
            )
            if node.kind is GraphNodeKind.REPOSITORY
            else node
            for node in nodes
        )
        self._nodes[repository_id] = stamped_nodes
        self._relationships[repository_id] = relationships
        return ProjectionResult(
            repository_id=repository_id,
            node_count=len(nodes),
            relationship_count=len(relationships),
            projected_at=projected_at,
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
        kind: GraphRelationshipKind | None = None,
        limit: int = 100,
    ) -> list[GraphNeighbor] | None:
        nodes_by_id = {node.id: node for node in self._nodes.get(repository_id, ())}
        if node_id not in nodes_by_id:
            return None

        neighbors: list[GraphNeighbor] = []
        for relationship in self._relationships.get(repository_id, ()):
            if kind is not None and relationship.kind is not kind:
                continue
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


_IMPACT_RELATIONSHIP_KINDS = (
    GraphRelationshipKind.CALLS,
    GraphRelationshipKind.IMPORTS,
    GraphRelationshipKind.INHERITS,
)


class InMemoryGraphIntelligenceRepository:
    """See module docstring — wraps an `InMemoryGraphRepository`'s data
    rather than keeping a separate store. `available` is a plain public
    attribute a test can flip to simulate Neo4j being unreachable — checked
    at the top of every method, mirroring `InMemoryGraphRepository`'s own
    flag (there, only `is_available()` checks it, since `GraphService`
    explicitly calls that before writing; here, every read method checks it
    directly, since `GraphIntelligenceService` has no equivalent pre-check
    and instead relies on the port itself raising `GraphUnavailableError`)."""

    def __init__(self, graph: InMemoryGraphRepository, *, available: bool = True) -> None:
        self._graph = graph
        self.available = available

    def _check_available(self) -> None:
        if not self.available:
            raise GraphUnavailableError("Neo4j unavailable (simulated)")

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
        self._check_available()
        nodes_by_id = {node.id: node for node in self._graph._nodes.get(repository_id, ())}
        if node_id not in nodes_by_id:
            return None

        allowed_kinds = (kind,) if kind is not None else _IMPACT_RELATIONSHIP_KINDS
        relationships = [
            r
            for r in self._graph._relationships.get(repository_id, ())
            if r.kind in allowed_kinds
        ]
        # UPSTREAM: follow a relationship backward (target -> source), i.e.
        # from the perspective of the current frontier node, its predecessors
        # are relationships where it's the *target*. DOWNSTREAM is the mirror.
        if direction is DependencyDirection.UPSTREAM:
            adjacency: dict[UUID, list[GraphRelationship]] = {}
            for r in relationships:
                adjacency.setdefault(r.target_id, []).append(r)

            def neighbors_of(current: UUID) -> list[tuple[UUID, GraphRelationship]]:
                return [(r.source_id, r) for r in adjacency.get(current, [])]
        else:
            adjacency = {}
            for r in relationships:
                adjacency.setdefault(r.source_id, []).append(r)

            def neighbors_of(current: UUID) -> list[tuple[UUID, GraphRelationship]]:
                return [(r.target_id, r) for r in adjacency.get(current, [])]

        visited: dict[UUID, tuple[int, GraphRelationshipKind]] = {}
        queue: deque[tuple[UUID, int]] = deque([(node_id, 0)])
        seen = {node_id}
        while queue:
            current, depth = queue.popleft()
            if depth == max_depth:
                continue
            for neighbor_id, rel in neighbors_of(current):
                if neighbor_id in seen:
                    continue
                seen.add(neighbor_id)
                visited[neighbor_id] = (depth + 1, rel.kind)
                queue.append((neighbor_id, depth + 1))

        ordered = sorted(visited.items(), key=lambda item: (item[1][0], str(item[0])))[:limit]
        impacted_nodes = tuple(
            ImpactedNode(node=nodes_by_id[nid], depth=d, relationship_kind=k)
            for nid, (d, k) in ordered
        )
        return ImpactAnalysisResult(
            starting_node_id=node_id,
            direction=direction,
            max_depth=max_depth,
            impacted_nodes=impacted_nodes,
        )

    async def get_path(
        self,
        repository_id: UUID,
        source_id: UUID,
        target_id: UUID,
        *,
        max_depth: int,
        kind: GraphRelationshipKind | None = None,
    ) -> DependencyPathResult | None:
        self._check_available()
        nodes_by_id = {node.id: node for node in self._graph._nodes.get(repository_id, ())}
        if source_id not in nodes_by_id or target_id not in nodes_by_id:
            return None

        if source_id == target_id:
            return DependencyPathResult(
                source_id=source_id, target_id=target_id, found=True,
                nodes=(nodes_by_id[source_id],), relationships=(), length=0,
            )

        allowed_kinds = (kind,) if kind is not None else _IMPACT_RELATIONSHIP_KINDS
        outgoing: dict[UUID, list[GraphRelationship]] = {}
        for r in self._graph._relationships.get(repository_id, ()):
            if r.kind in allowed_kinds:
                outgoing.setdefault(r.source_id, []).append(r)

        # Plain BFS, source -> target, directed, tracking the relationship
        # used to reach each node so the path can be reconstructed.
        came_from: dict[UUID, GraphRelationship] = {}
        queue: deque[tuple[UUID, int]] = deque([(source_id, 0)])
        seen = {source_id}
        while queue:
            current, depth = queue.popleft()
            if current == target_id:
                break
            if depth == max_depth:
                continue
            for r in outgoing.get(current, []):
                if r.target_id in seen:
                    continue
                seen.add(r.target_id)
                came_from[r.target_id] = r
                queue.append((r.target_id, depth + 1))
        else:
            return DependencyPathResult(
                source_id=source_id, target_id=target_id, found=False,
                nodes=(), relationships=(), length=None,
            )

        path_relationships: list[GraphRelationship] = []
        cursor = target_id
        while cursor != source_id:
            rel = came_from[cursor]
            path_relationships.append(rel)
            cursor = rel.source_id
        path_relationships.reverse()

        path_nodes = [nodes_by_id[source_id]]
        path_nodes.extend(nodes_by_id[r.target_id] for r in path_relationships)
        return DependencyPathResult(
            source_id=source_id,
            target_id=target_id,
            found=True,
            nodes=tuple(path_nodes),
            relationships=tuple(path_relationships),
            length=len(path_relationships),
        )

    async def get_statistics(self, repository_id: UUID, *, limit: int = 10) -> GraphStatistics:
        self._check_available()
        nodes = self._graph._nodes.get(repository_id, ())
        relationships = self._graph._relationships.get(repository_id, ())
        nodes_by_id = {n.id: n for n in nodes}

        total_files = sum(1 for n in nodes if n.kind is GraphNodeKind.FILE)
        total_symbols = sum(1 for n in nodes if n.kind is GraphNodeKind.SYMBOL)

        counts_by_kind = Counter(r.kind for r in relationships)
        relationships_by_kind = tuple(
            RelationshipKindCount(kind=kind, count=counts_by_kind.get(kind, 0))
            for kind in GraphRelationshipKind
        )

        in_degree = Counter(r.target_id for r in relationships)
        out_degree = Counter(r.source_id for r in relationships)
        highest_in_degree = tuple(
            NodeDegree(node=nodes_by_id[nid], degree=degree)
            for nid, degree in sorted(
                in_degree.items(), key=lambda item: (-item[1], str(item[0]))
            )[:limit]
        )
        highest_out_degree = tuple(
            NodeDegree(node=nodes_by_id[nid], degree=degree)
            for nid, degree in sorted(
                out_degree.items(), key=lambda item: (-item[1], str(item[0]))
            )[:limit]
        )

        repository_node = next(
            (n for n in nodes if n.kind is GraphNodeKind.REPOSITORY), None
        )
        projected_at = None
        if repository_node is not None:
            raw = repository_node.properties.get("projected_at")
            if isinstance(raw, str):
                projected_at = datetime.fromisoformat(raw)

        return GraphStatistics(
            repository_id=repository_id,
            total_nodes=len(nodes),
            total_files=total_files,
            total_symbols=total_symbols,
            total_relationships=len(relationships),
            relationships_by_kind=relationships_by_kind,
            highest_in_degree=highest_in_degree,
            highest_out_degree=highest_out_degree,
            projected_at=projected_at,
            freshness="not_projected" if projected_at is None else "fresh",
            computed_at=datetime.now(UTC),
        )

    async def get_insights(self, repository_id: UUID, *, limit: int = 20) -> GraphInsights:
        self._check_available()
        nodes = self._graph._nodes.get(repository_id, ())
        relationships = self._graph._relationships.get(repository_id, ())
        nodes_by_id = {n.id: n for n in nodes}

        imports_degree: Counter[UUID] = Counter()
        for r in relationships:
            if r.kind is GraphRelationshipKind.IMPORTS:
                imports_degree[r.source_id] += 1
                imports_degree[r.target_id] += 1
        most_connected_files = tuple(
            NodeDegree(node=nodes_by_id[nid], degree=degree)
            for nid, degree in sorted(
                imports_degree.items(), key=lambda item: (-item[1], str(item[0]))
            )[:limit]
            if degree > 0
        )

        hotspot_kinds = {GraphRelationshipKind.CALLS, GraphRelationshipKind.INHERITS}
        hotspot_degree: Counter[UUID] = Counter()
        for r in relationships:
            if r.kind in hotspot_kinds:
                hotspot_degree[r.source_id] += 1
                hotspot_degree[r.target_id] += 1
        dependency_hotspots = tuple(
            NodeDegree(node=nodes_by_id[nid], degree=degree)
            for nid, degree in sorted(
                hotspot_degree.items(), key=lambda item: (-item[1], str(item[0]))
            )[:limit]
            if degree > 0
        )

        isolated_files = [
            n
            for n in nodes
            if n.kind is GraphNodeKind.FILE and imports_degree.get(n.id, 0) == 0
        ]
        isolated_symbols = [
            n
            for n in nodes
            if n.kind is GraphNodeKind.SYMBOL and hotspot_degree.get(n.id, 0) == 0
        ]
        isolated_nodes = tuple((isolated_files + isolated_symbols)[:limit])

        mutual_pairs: list[MutualImportPair] = []
        imports_pairs = {
            (r.source_id, r.target_id)
            for r in relationships
            if r.kind is GraphRelationshipKind.IMPORTS
        }
        seen: set[frozenset[UUID]] = set()
        for source_id, target_id in imports_pairs:
            if (target_id, source_id) in imports_pairs:
                key = frozenset({source_id, target_id})
                if key not in seen:
                    seen.add(key)
                    a, b = sorted((source_id, target_id), key=str)
                    mutual_pairs.append(
                        MutualImportPair(file_a=nodes_by_id[a], file_b=nodes_by_id[b])
                    )
        mutual_import_pairs = tuple(mutual_pairs[:limit])

        return GraphInsights(
            repository_id=repository_id,
            most_connected_files=most_connected_files,
            dependency_hotspots=dependency_hotspots,
            isolated_nodes=isolated_nodes,
            mutual_import_pairs=mutual_import_pairs,
            unresolved_dependency_count=0,
            computed_at=datetime.now(UTC),
        )


# --- Phase 7 (RAG) fakes -----------------------------------------------------


class InMemoryChunkRepository:
    """Mirrors `SqlAlchemyChunkRepository`'s replace-on-reindex semantics and its
    two structural isolation guarantees — every read is scoped to one
    `repository_id`, and every read is bounded by an explicit `limit`. Real-
    backend coverage for the concrete implementation lives in
    tests/integration/test_postgres_rag_persistence.py (Postgres); this fake
    exists so the RAG application services and API routes can be exercised
    without a live database, matching the Phase 2-6 in-memory-fake precedent."""

    def __init__(self) -> None:
        self._chunks: dict[UUID, list[EmbeddedChunk]] = {}

    async def replace_chunks(
        self, repository_id: UUID, chunks: tuple[EmbeddedChunk, ...]
    ) -> None:
        # Full replacement — a re-index never leaves chunks for source that no
        # longer exists; an empty tuple clears the repository's index.
        self._chunks[repository_id] = list(chunks)

    async def get_existing_embeddings_by_hash(
        self, repository_id: UUID, embedding_model: str
    ) -> dict[str, tuple[float, ...]]:
        reuse: dict[str, tuple[float, ...]] = {}
        for embedded in self._chunks.get(repository_id, []):
            # Scoped to the model too: a vector from a different model must never
            # be reused (it lives in a different vector space).
            if embedded.embedding_model != embedding_model:
                continue
            content_hash = embedded.chunk.content_hash
            if content_hash not in reuse:
                reuse[content_hash] = embedded.embedding
        return reuse

    async def get_embeddings(
        self, repository_id: UUID, *, limit: int
    ) -> tuple[ChunkEmbedding, ...]:
        # Ordered by id so the (bounded) candidate window is deterministic across
        # runs, mirroring the real `ORDER BY id LIMIT :limit`.
        ordered = sorted(
            self._chunks.get(repository_id, []), key=lambda e: e.chunk.id.bytes
        )
        return tuple(
            ChunkEmbedding(chunk_id=e.chunk.id, embedding=e.embedding)
            for e in ordered[:limit]
        )

    async def get_chunks_by_ids(
        self, repository_id: UUID, chunk_ids: tuple[UUID, ...]
    ) -> dict[UUID, CodeChunk]:
        # Filtered by repository AND id — an id leaked from another repository is
        # simply absent from the result (defense in depth).
        wanted = set(chunk_ids)
        return {
            e.chunk.id: e.chunk
            for e in self._chunks.get(repository_id, [])
            if e.chunk.id in wanted
        }

    async def get_chunks_by_symbol_ids(
        self, repository_id: UUID, symbol_ids: tuple[UUID, ...], *, limit: int
    ) -> tuple[CodeChunk, ...]:
        if not symbol_ids:
            return ()
        wanted = set(symbol_ids)
        matching = [
            e.chunk
            for e in self._chunks.get(repository_id, [])
            if e.chunk.symbol_id is not None and e.chunk.symbol_id in wanted
        ]
        matching.sort(key=lambda c: (str(c.symbol_id), c.start_line, c.id.bytes))
        return tuple(matching[:limit])

    async def get_status(self, repository_id: UUID) -> IndexStatus:
        stored = self._chunks.get(repository_id, [])
        embedding_model = max((e.embedding_model for e in stored), default=None)
        return IndexStatus(
            repository_id=repository_id,
            indexed=len(stored) > 0,
            chunk_count=len(stored),
            embedding_model=embedding_model,
            last_indexed_at=datetime.now(UTC) if stored else None,
        )

    async def search_symbols(
        self, repository_id: UUID, symbol_names: tuple[str, ...], *, limit: int
    ) -> tuple[CodeChunk, ...]:
        if not symbol_names or limit <= 0:
            return ()
        names = [s.strip().lower() for s in symbol_names if s.strip()]
        if not names:
            return ()

        candidates: list[tuple[int, int, CodeChunk]] = []
        for embedded in self._chunks.get(repository_id, []):
            chunk = embedded.chunk
            if not chunk.symbol_qualified_name:
                continue
            qname = chunk.symbol_qualified_name.lower()
            matched_priority = None
            for name in names:
                if qname == name:
                    matched_priority = 0
                    break
                elif qname.endswith(f".{name}"):
                    matched_priority = min(
                        matched_priority if matched_priority is not None else 99, 1
                    )
                elif qname.startswith(f"{name}.") or f".{name}." in qname:
                    matched_priority = min(
                        matched_priority if matched_priority is not None else 99, 2
                    )
            if matched_priority is not None:
                candidates.append((matched_priority, len(chunk.symbol_qualified_name), chunk))

        candidates.sort(key=lambda item: (item[0], item[1], item[2].start_line, item[2].id.bytes))
        return tuple(c for _, _, c in candidates[:limit])

    async def search_lexical(
        self, repository_id: UUID, query: str, *, limit: int
    ) -> tuple[CodeChunk, ...]:
        if not query.strip() or limit <= 0:
            return ()
        terms = [t.lower() for t in extract_lexical_terms(query)]
        if not terms:
            return ()

        scored: list[tuple[float, CodeChunk]] = []
        for embedded in self._chunks.get(repository_id, []):
            chunk = embedded.chunk
            text_corpus = (
                f"{chunk.path} {chunk.symbol_qualified_name or ''} {chunk.content}".lower()
            )
            score = 0.0
            for term in terms:
                if term in text_corpus:
                    score += 1.0
                    if chunk.symbol_qualified_name and term in chunk.symbol_qualified_name.lower():
                        score += 0.5
                    if term in chunk.content.lower():
                        score += 0.5
            if score > 0.0:
                scored.append((score, chunk))

        scored.sort(key=lambda item: (-item[0], item[1].start_line, item[1].id.bytes))
        return tuple(c for _, c in scored[:limit])



class StubEmbeddingProvider:
    """A fully controllable `EmbeddingProvider` for RAG service unit tests.

    Returns a preset vector for an exact text (falling back to `default`), so a
    test can place a query and its intended-relevant chunk on the same axis and
    everything else orthogonal — giving precise, deterministic control over
    similarity scores and therefore over which retrieval branch is taken. Records
    every call (so a test can assert, e.g., that no embedding happened) and can
    simulate a provider outage with `fail=True` (raises `RagProviderError`)."""

    def __init__(
        self,
        vectors: dict[str, tuple[float, ...]] | None = None,
        *,
        default: tuple[float, ...] = (1.0, 0.0, 0.0),
        model_name: str = "stub-embed",
        fail: bool = False,
    ) -> None:
        self._vectors = vectors or {}
        self._default = default
        self._model_name = model_name
        self.fail = fail
        self.query_calls: list[str] = []
        self.document_calls: list[tuple[str, ...]] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return len(self._default)

    async def embed_documents(
        self, texts: tuple[str, ...]
    ) -> tuple[tuple[float, ...], ...]:
        if self.fail:
            raise RagProviderError("Simulated embedding provider outage")
        self.document_calls.append(texts)
        return tuple(self._vectors.get(text, self._default) for text in texts)

    async def embed_query(self, text: str) -> tuple[float, ...]:
        if self.fail:
            raise RagProviderError("Simulated embedding provider outage")
        self.query_calls.append(text)
        return self._vectors.get(text, self._default)


class ScriptedLlmProvider:
    """A controllable `LlmProvider` for RAG ask unit tests: returns a preset
    `reply`, records how many times it was asked to generate (and the last
    system/prompt it saw), and can simulate a model outage with `fail=True`.

    The recorded call count is what lets a test prove the crucial "no model call
    below the similarity floor" guarantee — the service must decline without ever
    invoking generation."""

    def __init__(
        self,
        reply: str = "A grounded answer from the retrieved code.",
        *,
        model_name: str = "scripted-llm",
        fail: bool = False,
    ) -> None:
        self._reply = reply
        self._model_name = model_name
        self.fail = fail
        self.calls = 0
        self.last_system: str | None = None
        self.last_prompt: str | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, *, system: str, prompt: str) -> str:
        self.calls += 1
        self.last_system = system
        self.last_prompt = prompt
        if self.fail:
            raise RagProviderError("Simulated LLM provider outage")
        return self._reply


class MappingSourceReader:
    """A `SourceReader` backed by an in-memory `{path: text}` map, for indexing
    unit tests that shouldn't touch the filesystem. A path absent from the map
    reads as `None` (missing/unreadable), exactly as the real reader signals a
    file it must skip — so the "one unreadable file is skipped, not fatal" path
    is testable without crafting real unreadable files."""

    def __init__(self, texts: dict[str, str]) -> None:
        self._texts = texts
        self.reads: list[tuple[str, str]] = []

    def read_text(self, workspace_path: str, relative_path: str) -> str | None:
        self.reads.append((workspace_path, relative_path))
        return self._texts.get(relative_path)
