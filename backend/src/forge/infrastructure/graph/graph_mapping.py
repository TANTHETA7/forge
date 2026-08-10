"""Pure PostgreSQL-entity -> graph-entity mapping.

Purpose:       Turn already-loaded Phase 3 (`ParsedFile`/`Symbol`) and Phase 4
                (`DependencyEdge`) data into `GraphNode`/`GraphRelationship`
                value objects, ready for `GraphRepository.project_repository`.
Responsibility: Pure computation only — no I/O, no Cypher, no `neo4j` driver
                import. Kept separate from `application/graph/service.py` so
                it's unit-testable with zero infrastructure, mirroring how
                `infrastructure/dependency_analysis/*` resolvers are pure
                computation over already-loaded data.
Depends on:    domain/graph/entities.py, domain/parsing/entities.py,
                domain/dependency_analysis/entities.py, domain/repository/entities.py.
Depended on by: application/graph/service.py.

Node kinds: Repository/File/Symbol. Relationship kinds: CONTAINS
(Repository->File, and CLASS Symbol->its METHOD Symbols, derived from
`Symbol.parent_symbol_id` — always reliable, no resolution needed), DEFINES
(File->Symbol), and IMPORTS/CALLS/INHERITS (derived from Phase 4's
`DependencyEdge`s — File->File for IMPORTS, Symbol->Symbol for CALLS/INHERITS).

Only RESOLVED `DependencyEdge`s become relationships: a Neo4j relationship
needs two real endpoint nodes, and an AMBIGUOUS/UNRESOLVED edge's
`target_file_id`/`target_symbol_id` is `None` by construction (Phase 4's own
resolution model) — there is nothing to point a relationship at. Such edges
remain queryable exactly where they already are, Phase 4's own
`GET .../dependencies` endpoint; Phase 5 does not duplicate them into a
placeholder/dangling graph node (see docs/architecture/05-knowledge-graph.md,
"Graph relationship model").
"""

from __future__ import annotations

from uuid import UUID

from forge.domain.dependency_analysis.entities import (
    DependencyEdge,
    DependencyKind,
    ResolutionStatus,
)
from forge.domain.graph.entities import (
    GraphNode,
    GraphNodeKind,
    GraphRelationship,
    GraphRelationshipKind,
)
from forge.domain.parsing.entities import ParsedFile, Symbol
from forge.domain.repository.entities import Repository

_DEPENDENCY_KIND_TO_GRAPH_KIND: dict[DependencyKind, GraphRelationshipKind] = {
    DependencyKind.IMPORTS: GraphRelationshipKind.IMPORTS,
    DependencyKind.CALLS: GraphRelationshipKind.CALLS,
    DependencyKind.INHERITS: GraphRelationshipKind.INHERITS,
}
# IMPORTS edges connect two files; CALLS/INHERITS connect two symbols — same
# RESOLVED-only rule, different id pair on the `DependencyEdge`.
_FILE_LEVEL_KINDS = frozenset({DependencyKind.IMPORTS})


def map_repository_graph(
    repository: Repository,
    files: list[ParsedFile],
    edges: list[DependencyEdge],
) -> tuple[tuple[GraphNode, ...], tuple[GraphRelationship, ...]]:
    """Map one repository's already-loaded Postgres state into the full node/
    relationship set `GraphRepository.project_repository` should write.

    `edges` may be empty (parsed but never analyzed, or analyzed with
    nothing resolvable) — not an error; the returned graph will simply have
    no IMPORTS relationships (and, from slice 2 onward, no CALLS/INHERITS
    either) yet.
    """
    nodes: list[GraphNode] = [_repository_node(repository)]
    relationships: list[GraphRelationship] = []

    for file in files:
        nodes.append(_file_node(repository.id, file))
        relationships.append(
            _structural_relationship(
                GraphRelationshipKind.CONTAINS, repository.id, repository.id, file.id
            )
        )
        for symbol in file.symbols:
            nodes.append(_symbol_node(repository.id, file.id, symbol))
            relationships.append(
                _structural_relationship(
                    GraphRelationshipKind.DEFINES, repository.id, file.id, symbol.id
                )
            )
            if symbol.parent_symbol_id is not None:
                # A METHOD's containing CLASS -> always reliable, derived
                # purely from structure (no resolution needed) — the
                # "future Class->Method CONTAINS" Phase 3's own Symbol
                # docstring already foreshadowed.
                relationships.append(
                    _structural_relationship(
                        GraphRelationshipKind.CONTAINS,
                        repository.id,
                        symbol.parent_symbol_id,
                        symbol.id,
                    )
                )

    for edge in edges:
        relationship = _map_dependency_edge(edge)
        if relationship is not None:
            relationships.append(relationship)

    return tuple(nodes), tuple(relationships)


def _repository_node(repository: Repository) -> GraphNode:
    return GraphNode(
        id=repository.id,
        kind=GraphNodeKind.REPOSITORY,
        repository_id=repository.id,
        properties={
            "project_id": str(repository.project_id),
            "display_name": repository.display_name,
        },
    )


def _file_node(repository_id: UUID, file: ParsedFile) -> GraphNode:
    return GraphNode(
        id=file.id,
        kind=GraphNodeKind.FILE,
        repository_id=repository_id,
        properties={
            "path": file.path,
            "language": file.language.value,
            "has_syntax_errors": file.has_syntax_errors,
        },
    )


def _symbol_node(repository_id: UUID, file_id: UUID, symbol: Symbol) -> GraphNode:
    return GraphNode(
        id=symbol.id,
        kind=GraphNodeKind.SYMBOL,
        repository_id=repository_id,
        properties={
            "file_id": str(file_id),
            "kind": symbol.kind.value,
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "parent_symbol_id": (
                str(symbol.parent_symbol_id) if symbol.parent_symbol_id is not None else None
            ),
            "start_line": symbol.location.start_line,
            "end_line": symbol.location.end_line,
        },
    )


def _structural_relationship(
    kind: GraphRelationshipKind, repository_id: UUID, source_id: UUID, target_id: UUID
) -> GraphRelationship:
    """A CONTAINS/DEFINES relationship — always derivable from structure
    alone, never traced back to a `DependencyEdge` (`dependency_edge_id=None`)."""
    return GraphRelationship(
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        repository_id=repository_id,
        dependency_edge_id=None,
        properties={},
    )


def _map_dependency_edge(edge: DependencyEdge) -> GraphRelationship | None:
    graph_kind = _DEPENDENCY_KIND_TO_GRAPH_KIND.get(edge.kind)
    if graph_kind is None or edge.resolution_status is not ResolutionStatus.RESOLVED:
        return None

    if edge.kind in _FILE_LEVEL_KINDS:
        source_id, target_id = edge.source_file_id, edge.target_file_id
    else:
        # CALLS/INHERITS connect two Symbol nodes, not File nodes. A RESOLVED
        # edge always has source_symbol_id set (it's the calling function/
        # method, or the subclass — see domain/dependency_analysis/entities.py).
        if edge.source_symbol_id is None:
            return None
        source_id, target_id = edge.source_symbol_id, edge.target_symbol_id

    if target_id is None:
        return None

    return GraphRelationship(
        source_id=source_id,
        target_id=target_id,
        kind=graph_kind,
        repository_id=edge.repository_id,
        dependency_edge_id=edge.id,
        properties={"raw_target_expression": edge.raw_target_expression},
    )
