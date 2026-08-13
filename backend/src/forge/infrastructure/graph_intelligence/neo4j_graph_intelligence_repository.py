"""Neo4j implementation of `domain/graph_intelligence/ports.py::GraphIntelligenceRepository`.

Purpose:       Multi-hop and aggregate graph queries — impact analysis,
                dependency paths, statistics, insights — over an
                already-projected repository's Neo4j graph.
Responsibility: Translate between the domain entities and Cypher only — no
                projection logic (that stays exclusively
                infrastructure/graph/neo4j_graph_repository.py's), no
                application orchestration. Reuses that module's `NODE_LABEL`/
                `REL_TYPE`/`record_to_node` rather than duplicating the
                label/type-name tables or the `Record`->`GraphNode`
                conversion (both were made module-level there specifically
                for this reuse — see that module's own docstring).
Depends on:    neo4j, domain/graph/entities.py, domain/graph_intelligence/
                {entities,ports}.py, domain/errors.py,
                infrastructure/graph/neo4j_graph_repository.py.
Depended on by: infrastructure/graph_intelligence/dependencies.py.

Impact analysis uses APOC's `apoc.path.expandConfig` (confirmed available
against the running `forge-neo4j` container — the image already ships with
`NEO4J_PLUGINS: '["apoc"]'`, see infra/docker/docker-compose.yml) rather
than a plain Cypher variable-length pattern (`[:TYPE*1..N]`). A plain
variable-length `MATCH` enumerates every *path* up to the depth bound, which
is exponential in branching factor for a hub node in a moderately-connected
graph — `apoc.path.expandConfig` with `uniqueness: 'NODE_GLOBAL', bfs: true`
performs a proper breadth-first traversal instead, visiting each reachable
node exactly once, at its true shortest depth, in time proportional to the
visited subgraph rather than the number of paths through it. This is the
concrete, verified resolution of the "avoid unbounded variable-length
traversals" / "do not create Cypher queries capable of accidentally
traversing an entire huge repository" requirements (see
docs/architecture/06-code-intelligence.md, "Performance").

`uniqueness: 'NODE_GLOBAL'` also means a cycle that loops back to the
starting node is pruned automatically during traversal (the start node is
marked visited before expansion begins) — the explicit `m.id <> $node_id`
filter below is kept anyway as defense-in-depth/documentation, not because
it's load-bearing.

Path queries use Neo4j's native `shortestPath()`. `max_depth` is
interpolated into the query text as a literal integer, not passed as a
Cypher parameter — empirically confirmed (not assumed) against the running
Neo4j instance that a parameter is rejected inside a variable-length
relationship pattern's bound (`*1..$max_depth` raises
`Neo.ClientError.Statement.SyntaxError`), while a literal integer bound
works. This is the same class of safe, non-string interpolation already
used for `NODE_LABEL`/`REL_TYPE` names elsewhere — `max_depth` is a
server-validated `int` by the time it reaches this module, never raw
client text, so there is no injection surface.

Every public method optionally enforces `query_timeout_seconds` via
`asyncio.wait_for(...)` around the whole `execute_read` call, not via
`neo4j.Query(text, timeout=...)`. That `Query`-level per-statement timeout
was tried first and empirically confirmed (not assumed) to be rejected at
runtime — `ValueError: Query object is only supported for session.run` —
when used inside a managed transaction (`tx.run(...)` within
`execute_read`/`execute_write`, which this module uses throughout for the
driver's automatic retry behavior, same as
infrastructure/graph/neo4j_graph_repository.py). `asyncio.wait_for` is a
transaction-agnostic alternative: if the whole read (including the
driver's own retries) exceeds the budget, the call is cancelled and
translated to `GraphUnavailableError`, same as any other Neo4j-unreachable
outcome (see docs/architecture/06-code-intelligence.md, "Performance").
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Concatenate, ParamSpec, TypeVar
from uuid import UUID

from neo4j import AsyncManagedTransaction, AsyncSession

from forge.domain.errors import GraphUnavailableError
from forge.domain.graph.entities import GraphNodeKind, GraphRelationship, GraphRelationshipKind
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
from forge.infrastructure.graph.neo4j_driver import UNAVAILABLE_EXCEPTIONS
from forge.infrastructure.graph.neo4j_graph_repository import (
    NODE_LABEL,
    REL_TYPE,
    TYPE_TO_KIND,
    as_property_dict,
    record_to_node,
)

# The relationship kinds impact analysis (and path queries) traverse by
# default — deliberately excludes CONTAINS/DEFINES: a file's containment by
# its repository, or a symbol's definition in its file, isn't a "could be
# affected if this changes" relationship (see docs/architecture/
# 06-code-intelligence.md, "Impact analysis").
_IMPACT_RELATIONSHIP_KINDS: tuple[GraphRelationshipKind, ...] = (
    GraphRelationshipKind.CALLS,
    GraphRelationshipKind.IMPORTS,
    GraphRelationshipKind.INHERITS,
)

_TxParams = ParamSpec("_TxParams")
_TxResult = TypeVar("_TxResult")


def _relationship_filter(direction: DependencyDirection, kind: GraphRelationshipKind | None) -> str:
    """Build an APOC `relationshipFilter` string — e.g. `"CALLS<|IMPORTS<|INHERITS<"`
    for UPSTREAM with no `kind` restriction, or `"CALLS<"` alone if narrowed.
    `<` traverses a type only against its incoming direction (i.e. walks
    from a relationship's target back to its source — UPSTREAM, "what
    depends on this"); `>` is the mirror, outgoing-only (DOWNSTREAM, "what
    this depends on"). Every type name comes from this package's own
    trusted `REL_TYPE` map — never client-supplied text."""
    kinds = (kind,) if kind is not None else _IMPACT_RELATIONSHIP_KINDS
    arrow = "<" if direction is DependencyDirection.UPSTREAM else ">"
    return "|".join(f"{REL_TYPE[k]}{arrow}" for k in kinds)


def _path_relationship_pattern(kind: GraphRelationshipKind | None) -> str:
    """Build the relationship-type portion of a directed pattern, e.g.
    `":CALLS|IMPORTS|INHERITS"` or `":CALLS"` — same trusted-map sourcing as
    `_relationship_filter`, just without a direction arrow (path queries are
    always directed source->target, see module docstring)."""
    kinds = (kind,) if kind is not None else _IMPACT_RELATIONSHIP_KINDS
    return ":" + "|".join(REL_TYPE[k] for k in kinds)


class Neo4jGraphIntelligenceRepository:
    """A `GraphIntelligenceRepository` backed by Neo4j via the async driver.

    `query_timeout_seconds`, when given, bounds every public method's whole
    `execute_read` call via `asyncio.wait_for` (see module docstring) —
    sourced from `Settings.graph_query_timeout_seconds` by the FastAPI DI
    wiring in infrastructure/graph_intelligence/dependencies.py.
    """

    def __init__(
        self, session: AsyncSession, *, query_timeout_seconds: float | None = None
    ) -> None:
        self._session = session
        self._timeout = query_timeout_seconds

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
        return await self._run(
            _get_impact_tx, repository_id, node_id, direction, max_depth, kind, limit
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
        return await self._run(_get_path_tx, repository_id, source_id, target_id, max_depth, kind)

    async def get_statistics(self, repository_id: UUID, *, limit: int) -> GraphStatistics:
        return await self._run(_get_statistics_tx, repository_id, limit)

    async def get_insights(self, repository_id: UUID, *, limit: int) -> GraphInsights:
        return await self._run(_get_insights_tx, repository_id, limit)

    async def _run(
        self,
        tx_function: Callable[
            Concatenate[AsyncManagedTransaction, _TxParams], Awaitable[_TxResult]
        ],
        *args: _TxParams.args,
        **kwargs: _TxParams.kwargs,
    ) -> _TxResult:
        try:
            if self._timeout is None:
                return await self._session.execute_read(tx_function, *args, **kwargs)
            return await asyncio.wait_for(
                self._session.execute_read(tx_function, *args, **kwargs), timeout=self._timeout
            )
        except UNAVAILABLE_EXCEPTIONS as exc:
            raise GraphUnavailableError(f"Neo4j unavailable: {exc}") from exc
        except TimeoutError as exc:
            raise GraphUnavailableError(
                f"Neo4j query exceeded the {self._timeout}s timeout"
            ) from exc


async def _get_impact_tx(
    tx: AsyncManagedTransaction,
    repository_id: UUID,
    node_id: UUID,
    direction: DependencyDirection,
    max_depth: int,
    kind: GraphRelationshipKind | None,
    limit: int,
) -> ImpactAnalysisResult | None:
    exists_result = await tx.run(
        "MATCH (n:Node {id: $node_id, repository_id: $repository_id}) RETURN n LIMIT 1",
        node_id=str(node_id),
        repository_id=str(repository_id),
    )
    if await exists_result.single() is None:
        return None

    result = await tx.run(
        "MATCH (n:Node {id: $node_id, repository_id: $repository_id}) "
        "CALL apoc.path.expandConfig(n, {"
        "relationshipFilter: $rel_filter, minLevel: 1, maxLevel: $max_depth, "
        "uniqueness: 'NODE_GLOBAL', bfs: true, limit: $limit"
        "}) YIELD path "
        "WITH last(nodes(path)) AS m, length(path) AS depth, "
        "last(relationships(path)) AS lastRel "
        "WHERE m.repository_id = $repository_id AND m.id <> $node_id "
        "RETURN m, labels(m) AS labels, depth, type(lastRel) AS rel_kind "
        "ORDER BY depth, m.id",
        node_id=str(node_id),
        repository_id=str(repository_id),
        rel_filter=_relationship_filter(direction, kind),
        max_depth=max_depth,
        limit=limit,
    )
    impacted_nodes = [
        ImpactedNode(
            node=record_to_node(dict(record["m"]), record["labels"]),
            depth=record["depth"],
            relationship_kind=TYPE_TO_KIND[record["rel_kind"]],
        )
        async for record in result
    ]
    return ImpactAnalysisResult(
        starting_node_id=node_id,
        direction=direction,
        max_depth=max_depth,
        impacted_nodes=tuple(impacted_nodes),
    )


async def _get_path_tx(
    tx: AsyncManagedTransaction,
    repository_id: UUID,
    source_id: UUID,
    target_id: UUID,
    max_depth: int,
    kind: GraphRelationshipKind | None,
) -> DependencyPathResult | None:
    exists_result = await tx.run(
        "MATCH (n:Node {repository_id: $repository_id}) WHERE n.id IN [$source_id, $target_id] "
        "RETURN collect(n.id) AS ids",
        repository_id=str(repository_id),
        source_id=str(source_id),
        target_id=str(target_id),
    )
    exists_record = await exists_result.single()
    found_ids = set(exists_record["ids"]) if exists_record is not None else set()
    if str(source_id) not in found_ids or str(target_id) not in found_ids:
        return None

    if source_id == target_id:
        node_result = await tx.run(
            "MATCH (n:Node {id: $source_id, repository_id: $repository_id}) "
            "RETURN n, labels(n) AS labels",
            source_id=str(source_id),
            repository_id=str(repository_id),
        )
        node_record = await node_result.single()
        assert node_record is not None  # existence already confirmed above
        node = record_to_node(dict(node_record["n"]), node_record["labels"])
        return DependencyPathResult(
            source_id=source_id, target_id=target_id, found=True,
            nodes=(node,), relationships=(), length=0,
        )

    # `max_depth` is interpolated as a literal integer — see module docstring
    # for why it cannot be a Cypher parameter inside shortestPath()'s bound.
    rel_pattern = _path_relationship_pattern(kind)
    result = await tx.run(
        "MATCH (a:Node {id: $source_id, repository_id: $repository_id}), "
        "(b:Node {id: $target_id, repository_id: $repository_id}) "
        f"MATCH p = shortestPath((a)-[{rel_pattern}*1..{max_depth}]->(b)) "
        "RETURN [n IN nodes(p) | n] AS path_nodes, "
        "[n IN nodes(p) | labels(n)] AS path_labels, "
        "[r IN relationships(p) | r] AS path_rels, "
        "[r IN relationships(p) | type(r)] AS path_rel_types",
        source_id=str(source_id),
        target_id=str(target_id),
        repository_id=str(repository_id),
    )
    path_record = await result.single()
    if path_record is None:
        return DependencyPathResult(
            source_id=source_id, target_id=target_id, found=False,
            nodes=(), relationships=(), length=None,
        )

    path_nodes = tuple(
        record_to_node(dict(node_data), labels)
        for node_data, labels in zip(
            path_record["path_nodes"], path_record["path_labels"], strict=True
        )
    )
    path_relationships = tuple(
        _relationship_from_path_element(dict(rel_data), rel_type, repository_id)
        for rel_data, rel_type in zip(
            path_record["path_rels"], path_record["path_rel_types"], strict=True
        )
    )
    return DependencyPathResult(
        source_id=source_id,
        target_id=target_id,
        found=True,
        nodes=path_nodes,
        relationships=path_relationships,
        length=len(path_relationships),
    )


def _relationship_from_path_element(
    raw: dict[str, object], rel_type: str, repository_id: UUID
) -> GraphRelationship:
    """Convert one relationship encountered along a `shortestPath()` result
    into a `GraphRelationship` — reads `source_id`/`target_id`/
    `dependency_edge_id` from the relationship's own stored properties
    (written by `infrastructure/graph/neo4j_graph_repository.py`'s
    `_relationship_row`) rather than `startNode`/`endNode`, since those are
    already exactly the values needed and avoid an extra property lookup."""
    properties = dict(raw)
    source_id = UUID(str(properties.pop("source_id")))
    target_id = UUID(str(properties.pop("target_id")))
    properties.pop("repository_id", None)
    raw_dependency_edge_id = properties.pop("dependency_edge_id", None)
    return GraphRelationship(
        source_id=source_id,
        target_id=target_id,
        kind=TYPE_TO_KIND[rel_type],
        repository_id=repository_id,
        dependency_edge_id=(
            UUID(str(raw_dependency_edge_id)) if raw_dependency_edge_id is not None else None
        ),
        properties=as_property_dict(properties),
    )


async def _get_statistics_tx(
    tx: AsyncManagedTransaction, repository_id: UUID, limit: int
) -> GraphStatistics:
    """Four small aggregate queries, one managed transaction — node counts by
    label, relationship counts by type, and the two degree-ranking top-N
    lists. Each is O(this repository's own node/relationship count), scoped
    by the same `repository_id` property/index every other query in this
    package already relies on — not a new performance risk class (see
    docs/architecture/06-code-intelligence.md, "Performance").

    `freshness` here is only a placeholder ("not_projected" vs. "fresh") —
    this method has no access to PostgreSQL's `parsed_files.parsed_at`, so
    it cannot tell "fresh" from "stale" on its own.
    `GraphIntelligenceService.get_statistics` always recomputes this field
    correctly before returning it to a caller (see that module's own
    docstring)."""
    repo_id = str(repository_id)

    node_counts_result = await tx.run(
        "MATCH (n:Node {repository_id: $repository_id}) "
        "RETURN labels(n)[0] AS label, count(*) AS c",
        repository_id=repo_id,
    )
    node_counts = {record["label"]: record["c"] async for record in node_counts_result}
    total_files = node_counts.get(NODE_LABEL[GraphNodeKind.FILE], 0)
    total_symbols = node_counts.get(NODE_LABEL[GraphNodeKind.SYMBOL], 0)
    total_nodes = sum(node_counts.values())

    # One query per relationship type (`UNION ALL`), each anchored on its own
    # relationship type, rather than one label-less `MATCH ()-[r {...}]->()`
    # — Neo4j has no property index on relationships here, so a type-less
    # relationship match can only be answered by scanning every relationship
    # in the whole database (same `AllNodesScan`-class problem `:Node` fixes
    # for nodes — see neo4j_driver.py's docstring — but relationship
    # property indexes are per-type in Neo4j 5, so the fix here is simply to
    # always give it the type it's actually counting, which every caller of
    # this method already knows statically from `GraphRelationshipKind`).
    rel_counts_query = " UNION ALL ".join(
        f"MATCH ()-[r:{REL_TYPE[kind]} {{repository_id: $repository_id}}]->() "
        f"RETURN '{REL_TYPE[kind]}' AS kind, count(r) AS c"
        for kind in GraphRelationshipKind
    )
    rel_counts_result = await tx.run(rel_counts_query, repository_id=repo_id)
    raw_rel_counts = {record["kind"]: record["c"] async for record in rel_counts_result}
    relationships_by_kind = tuple(
        RelationshipKindCount(kind=kind, count=raw_rel_counts.get(REL_TYPE[kind], 0))
        for kind in GraphRelationshipKind
    )
    total_relationships = sum(entry.count for entry in relationships_by_kind)

    in_degree_result = await tx.run(
        "MATCH (n:Node {repository_id: $repository_id})<-[r {repository_id: $repository_id}]-() "
        "RETURN n, labels(n) AS labels, count(r) AS degree "
        "ORDER BY degree DESC, n.id LIMIT $limit",
        repository_id=repo_id,
        limit=limit,
    )
    highest_in_degree = tuple(
        [
            NodeDegree(
                node=record_to_node(dict(record["n"]), record["labels"]), degree=record["degree"]
            )
            async for record in in_degree_result
        ]
    )

    out_degree_result = await tx.run(
        "MATCH (n:Node {repository_id: $repository_id})-[r {repository_id: $repository_id}]->() "
        "RETURN n, labels(n) AS labels, count(r) AS degree "
        "ORDER BY degree DESC, n.id LIMIT $limit",
        repository_id=repo_id,
        limit=limit,
    )
    highest_out_degree = tuple(
        [
            NodeDegree(
                node=record_to_node(dict(record["n"]), record["labels"]), degree=record["degree"]
            )
            async for record in out_degree_result
        ]
    )

    projected_at_result = await tx.run(
        "MATCH (r:Repository {id: $repository_id}) RETURN r.projected_at AS projected_at",
        repository_id=repo_id,
    )
    projected_at_record = await projected_at_result.single()
    raw_projected_at = (
        projected_at_record["projected_at"] if projected_at_record is not None else None
    )
    projected_at = raw_projected_at.to_native() if raw_projected_at is not None else None

    return GraphStatistics(
        repository_id=repository_id,
        total_nodes=total_nodes,
        total_files=total_files,
        total_symbols=total_symbols,
        total_relationships=total_relationships,
        relationships_by_kind=relationships_by_kind,
        highest_in_degree=highest_in_degree,
        highest_out_degree=highest_out_degree,
        projected_at=projected_at,
        freshness="not_projected" if projected_at is None else "fresh",
        computed_at=datetime.now(UTC),
    )


async def _get_insights_tx(
    tx: AsyncManagedTransaction, repository_id: UUID, limit: int
) -> GraphInsights:
    """Five small, cheap, explainable queries — no scoring/weighting, every
    value a plain graph fact (see docs/architecture/06-code-intelligence.md,
    "Insights"). `unresolved_dependency_count` is always `0` here — this
    method has no PostgreSQL access; `GraphIntelligenceService.get_insights`
    always overwrites it with the real count from Phase 4's data."""
    repo_id = str(repository_id)

    most_connected_result = await tx.run(
        "MATCH (f:File {repository_id: $repository_id}) "
        "OPTIONAL MATCH (f)-[r:IMPORTS {repository_id: $repository_id}]-() "
        "WITH f, count(r) AS degree WHERE degree > 0 "
        "RETURN f, labels(f) AS labels, degree "
        "ORDER BY degree DESC, f.id LIMIT $limit",
        repository_id=repo_id,
        limit=limit,
    )
    most_connected_files = tuple(
        [
            NodeDegree(
                node=record_to_node(dict(record["f"]), record["labels"]), degree=record["degree"]
            )
            async for record in most_connected_result
        ]
    )

    hotspots_result = await tx.run(
        "MATCH (s:Symbol {repository_id: $repository_id}) "
        "OPTIONAL MATCH (s)-[r:CALLS|INHERITS {repository_id: $repository_id}]-() "
        "WITH s, count(r) AS degree WHERE degree > 0 "
        "RETURN s, labels(s) AS labels, degree "
        "ORDER BY degree DESC, s.id LIMIT $limit",
        repository_id=repo_id,
        limit=limit,
    )
    dependency_hotspots = tuple(
        [
            NodeDegree(
                node=record_to_node(dict(record["s"]), record["labels"]), degree=record["degree"]
            )
            async for record in hotspots_result
        ]
    )

    isolated_files_result = await tx.run(
        "MATCH (f:File {repository_id: $repository_id}) "
        "WHERE NOT (f)-[:IMPORTS {repository_id: $repository_id}]-() "
        "RETURN f, labels(f) AS labels LIMIT $limit",
        repository_id=repo_id,
        limit=limit,
    )
    isolated_files = [
        record_to_node(dict(record["f"]), record["labels"])
        async for record in isolated_files_result
    ]
    isolated_symbols_result = await tx.run(
        "MATCH (s:Symbol {repository_id: $repository_id}) "
        "WHERE NOT (s)-[:CALLS|INHERITS {repository_id: $repository_id}]-() "
        "RETURN s, labels(s) AS labels LIMIT $limit",
        repository_id=repo_id,
        limit=limit,
    )
    isolated_symbols = [
        record_to_node(dict(record["s"]), record["labels"])
        async for record in isolated_symbols_result
    ]
    isolated_nodes = tuple((isolated_files + isolated_symbols)[:limit])

    mutual_imports_result = await tx.run(
        "MATCH (a:File {repository_id: $repository_id})"
        "-[:IMPORTS {repository_id: $repository_id}]->"
        "(b:File {repository_id: $repository_id}) "
        "WHERE (b)-[:IMPORTS {repository_id: $repository_id}]->(a) AND a.id < b.id "
        "RETURN a, labels(a) AS a_labels, b, labels(b) AS b_labels LIMIT $limit",
        repository_id=repo_id,
        limit=limit,
    )
    mutual_import_pairs = tuple(
        [
            MutualImportPair(
                file_a=record_to_node(dict(record["a"]), record["a_labels"]),
                file_b=record_to_node(dict(record["b"]), record["b_labels"]),
            )
            async for record in mutual_imports_result
        ]
    )

    return GraphInsights(
        repository_id=repository_id,
        most_connected_files=most_connected_files,
        dependency_hotspots=dependency_hotspots,
        isolated_nodes=isolated_nodes,
        mutual_import_pairs=mutual_import_pairs,
        unresolved_dependency_count=0,
        computed_at=datetime.now(UTC),
    )
