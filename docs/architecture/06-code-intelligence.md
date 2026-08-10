# Phase 6 — Code Intelligence & Impact Analysis

This document describes the Phase 6 implementation as it actually exists in
the codebase. It does not describe aspirational or future behavior; where a
capability is deliberately not implemented, it is called out under "Known
limitations" rather than implied elsewhere.

## 1. Purpose

Phase 5 gave Forge a Neo4j projection of Phase 3/4's PostgreSQL data —
nodes for repositories/files/symbols, relationships for
CONTAINS/DEFINES/IMPORTS/CALLS/INHERITS — but only exposed **raw browsing**
of it: list all nodes, list all relationships, list one node's direct
neighbors. None of that answers the questions that make a dependency graph
actually useful: "what would break if I change this function", "is there a
dependency path from A to B", "which files sit at the center of this
codebase", "does this repository have circular imports".

Phase 6 turns Phase 5's projection into a **query/analysis layer**:
multi-hop impact analysis, shortest dependency paths, degree-based
statistics, and a handful of narrow, explainable structural insights — six
capabilities in total (dependency exploration, upstream/downstream
traversal, impact analysis, dependency-path queries, graph statistics,
repository insights). Every one of them is a **deterministic graph query**.
There is no LLM, no natural-language generation, no AI-scored
recommendation anywhere in this phase — every response is a plain,
reproducible graph fact traceable back to the exact Cypher query that
produced it.

## 2. Relationship to Phase 5

Phase 6 performs **no new resolution and no new projection**. It reads the
graph Phase 5 already built and never writes to it (with one small,
additive exception — see §11, `projected_at`). PostgreSQL remains the sole
source of truth, unchanged; Neo4j remains a derived, rebuildable projection
of it, unchanged. Phase 6 does not duplicate Phase 4's dependency-resolution
logic and does not move it into this phase — every CALLS/IMPORTS/INHERITS
edge Phase 6 traverses is one Phase 5 already projected from a `RESOLVED`
Phase 4 `DependencyEdge`.

**Capability 1 (dependency exploration) reuses Phase 5 verbatim.** Rather
than build a second single-hop traversal query, `GraphRepository.get_neighbors`
(Phase 5's own method) was extended with one additive, backward-compatible
parameter — `kind: GraphRelationshipKind | None = None` — and
`GraphIntelligenceService.get_dependencies`/`get_dependents` are thin
wrappers that translate Phase 6's `DependencyDirection` vocabulary to Phase
5's existing `"incoming"`/`"outgoing"` strings and call it directly. No new
Cypher, no new port method, no new entity for this capability (see §3 for
why).

Capabilities 3–6 (impact, paths, statistics, insights) are genuinely new
query shapes — bounded multi-hop traversal, shortest path, aggregation —
that don't belong on Phase 5's "projection + raw browsing" port. These get
a new port and a new Neo4j-backed implementation, described below.

## 3. Architecture

```
api/graph_intelligence.py
      │  thin — no Cypher, no driver code
      ▼
application/graph_intelligence/service.py     GraphIntelligenceService
      │  orchestration only; depends on BOTH the existing Phase 5
      │  GraphRepository (for dependencies/dependents + existence checks)
      │  AND the new GraphIntelligenceRepository (impact/path/statistics/
      │  insights) AND the existing RepositoryRepository/ParsedFileRepository/
      │  DependencyEdgeRepository (repository existence, freshness,
      │  unresolved-count passthrough)
      ▼
domain/graph_intelligence/{entities,ports}.py
      │  DependencyDirection, ImpactedNode, ImpactAnalysisResult,
      │  DependencyPathResult, RelationshipKindCount, NodeDegree,
      │  GraphStatistics, MutualImportPair, GraphInsights
      │  GraphIntelligenceRepository (port) — impact/path/statistics/
      │  insights only; dependencies/dependents reuse Phase 5's port as-is
      ▼
infrastructure/graph_intelligence/*.py        Neo4jGraphIntelligenceRepository
      │                                        (all new Cypher/APOC),
      │                                        dependencies.py (DI wiring,
      │                                        reuses Phase 5's
      │                                        get_neo4j_session)
      ▼
Neo4j (bolt://localhost:7687)
```

This mirrors the layering every earlier phase already established: `domain`
has zero framework/driver imports; `application` depends only on ports;
`infrastructure` is the only layer that imports the `neo4j` package or
constructs Cypher; `api` is thin HTTP translation. `GraphIntelligenceService`
is the one place in the codebase that holds references to *both* a Neo4j
port and PostgreSQL ports simultaneously — deliberate, since freshness
classification (§11) needs exactly that.

`Neo4jGraphIntelligenceRepository` reuses
`infrastructure/graph/neo4j_graph_repository.py`'s own `NODE_LABEL`,
`REL_TYPE`, `TYPE_TO_KIND`, `record_to_node`, and `as_property_dict` (all
made module-level there specifically for this reuse) rather than
duplicating the label/type-name tables or the `Record`→`GraphNode`
conversion.

## 4. Domain model

`domain/graph_intelligence/entities.py`:

- **`DependencyDirection`** (`UPSTREAM`/`DOWNSTREAM`) — see §5.
- **No `DependencyResult` entity.** Dependencies/dependents reuse
  `domain/graph/entities.py::GraphNeighbor` (`node`, `relationship_kind`,
  `direction`) as-is — a new entity would duplicate that exact shape with
  no behavioral difference.
- **`ImpactedNode`** — one node reachable from an impact-analysis starting
  node: `node`, `depth` (minimum hops), `relationship_kind` (the kind of
  the nearest hop that reached it at that minimum depth — representative,
  not exhaustive, when multiple kinds tie at the same depth).
- **`ImpactAnalysisResult`** — `starting_node_id`, `direction`, `max_depth`,
  `impacted_nodes` (never includes the starting node itself).
- **`DependencyPathResult`** — `source_id`, `target_id`, `found`, `nodes`,
  `relationships`, `length`. `found=False` is a normal outcome (§7), not an
  error.
- **`RelationshipKindCount`** / **`NodeDegree`** — small counting entities
  used by statistics and insights.
- **`GraphStatistics`** — repository-wide counts, per-kind relationship
  counts (all 5 kinds, always zero-filled), top-N in-/out-degree rankings,
  `projected_at`/`freshness`/`computed_at`.
- **`MutualImportPair`** / **`GraphInsights`** — the six insight fields
  (§9).

## 5. Graph query model / upstream-downstream semantics

Defined once, applied uniformly across every relationship kind — all of
which already point "source depends on target" (IMPORTS: importer→imported;
CALLS: caller→callee; INHERITS: subclass→superclass, all established by
Phase 4/5):

- **DOWNSTREAM(X)** = nodes reachable via **outgoing** edges from X — "what
  X depends on."
- **UPSTREAM(X)** = nodes reachable via **incoming** edges into X — "what
  depends on X."

This requires no per-relationship-kind special-casing anywhere in Phase 6.

**Capability 1 (dependencies/dependents)** — `GET .../dependencies` returns
DOWNSTREAM neighbors, `GET .../dependents` returns UPSTREAM neighbors, both
single-hop. **Important, and a documented behavioral detail (see the real
end-to-end test's own comment):** with no `kind` filter, these return
neighbors of **any** relationship kind, including the structural
CONTAINS/DEFINES edges every node already has (a symbol's defining file, a
file's owning repository) — not just CALLS/IMPORTS/INHERITS. A caller who
wants only "real" dependency relationships passes `kind=` explicitly (e.g.
`kind=calls`). This is a deliberate consequence of reusing Phase 5's
`get_neighbors` unmodified in its default behavior — Capability 1 is
"direct neighbors," not "direct code-dependency neighbors" — and is
distinct from impact analysis/path queries (§6/§7), which *do* default to
excluding CONTAINS/DEFINES.

## 6. Impact analysis

**Default direction is UPSTREAM** — "if I change this node, what could be
affected" is the transitive closure of everything that depends on it,
matching industry-standard blast-radius analysis. `direction` stays an
explicit, documented parameter, so downstream impact ("what would I need to
also verify, given what this relies on") remains one call away.

- Traversal is restricted, by default, to `CALLS`/`IMPORTS`/`INHERITS` —
  `CONTAINS`/`DEFINES` are excluded, since a file's containment by its
  repository, or a symbol's definition in its file, isn't a "could be
  affected if this changes" relationship. Narrowable via `kind`.
- `max_depth` is required, server-clamped 1–10 (`Settings.graph_max_impact_depth`),
  default 3.
- The starting node **never** appears in its own result, even when a cycle
  routes back to it within `max_depth`.
- Each impacted node reports its **minimum** depth and the relationship
  kind of whichever hop produced that minimum — a representative value
  when multiple paths/kinds tie at that depth, not an exhaustive multi-path
  report (a disclosed, deterministic simplification, not a hidden
  inconsistency).

**Implementation**: `apoc.path.expandConfig`, not a plain Cypher
variable-length pattern. A plain `[:TYPE*1..N]` `MATCH` enumerates every
*path* up to the depth bound — exponential in branching factor for a hub
node in a moderately-connected graph. `apoc.path.expandConfig` with
`uniqueness: 'NODE_GLOBAL', bfs: true` performs a proper breadth-first
traversal instead, visiting each reachable node exactly once at its true
shortest depth, in time proportional to the visited subgraph rather than
the number of paths through it — confirmed available against the running
`forge-neo4j` container (the image ships `NEO4J_PLUGINS: '["apoc"]'`), not
assumed. `uniqueness: 'NODE_GLOBAL'` also prunes a cycle back to the
starting node automatically during traversal; the explicit `m.id <>
$node_id` filter is kept anyway as defense-in-depth.

**Static analysis only — documented explicitly, here and in code
docstrings.** Impact analysis is derived entirely from Phase 4's
statically-resolved edges. It does **not** model dynamic dispatch, runtime
polymorphism, reflection, or conditional imports — it inherits Phase 4's
own already-disclosed resolution limitations rather than introducing new
ones. A node's absence from the result is not a safety guarantee; its
presence is not a guarantee of an actual behavioral change. Concretely: a
`self.foo()` / `this.foo()` call is Phase 4's own documented
one-level-only-self-call limitation, and is simply invisible to impact
analysis exactly as it's invisible to Phase 4's own `/dependencies`
endpoint — confirmed directly by the real end-to-end test, where
`Animal.speak` (only ever reached via an unresolved `self.speak()`) shows
zero impact even though `Dog.bark` textually calls it.

## 7. Path semantics

**Directed shortest path**, source → target, via Neo4j's native
`shortestPath()` — not an undirected walk. A "dependency path" should read
as a coherent chain of "depends on" hops; an undirected search could mix
forward and backward edges into a confusing answer. If no directed path
exists within `max_depth`, the result is `found=False` — never a silent
fallback to an undirected search.

**Shortest path is the deliberate default semantic**, not "all paths" or
"longest path": it is Neo4j's native, optimized, cycle-safe algorithm; it
is the smallest and most directly useful single answer to "is there a path
and what is it"; and it matches how every comparable tool (dependency
graphs, social graphs) defaults this question.

- `max_depth` bounds the search — server-clamped 1–15
  (`Settings.graph_max_path_depth`), default 6.
- `kind` narrows the relationship-type set — same default (`CALLS`/
  `IMPORTS`/`INHERITS`) and same rationale as impact analysis.
- **`source_id == target_id`** is well-defined, not an error:
  `found=True, nodes=(that node,), relationships=(), length=0`.
- **No-path is a valid 200 result, not a 404.** If both `source_id` and
  `target_id` exist (validated first) but no directed path connects them
  within `max_depth`, the response is `found=False`, empty `nodes`/
  `relationships`, `length=None`. 404 is reserved for when `source_id`/
  `target_id` itself doesn't exist within the repository — confirmed
  directly by `test_no_reverse_fallback...`-style integration tests (an
  IMPORTS edge only one direction produces `found=False` for the reverse
  query, not an error).
- Cycles are handled safely and natively by `shortestPath()` — no custom
  cycle-detection code.

`max_depth` is interpolated into the Cypher text as a literal integer, not
passed as a Cypher parameter — empirically confirmed against the running
Neo4j instance that a parameter is rejected inside a variable-length
relationship pattern's bound (`*1..$max_depth` raises
`Neo.ClientError.Statement.SyntaxError`), while a literal integer bound
works. This is the same class of safe, non-string interpolation already
used for `NODE_LABEL`/`REL_TYPE` names elsewhere in Phase 5 —`max_depth` is
a server-validated `int` by the time it reaches this code, never raw
client text, so there is no injection surface.

## 8. Statistics

One aggregate snapshot per repository (`GET .../graph/statistics`):
`total_nodes`/`total_files`/`total_symbols`/`total_relationships`, a
per-kind relationship count (all 5 kinds always present, zero-filled —
never silently omitted), and the top-N highest in-/out-degree nodes,
computed **over all relationship kinds combined** — a general "most
central" signal, distinct from Insights' kind-scoped rankings (§9). `limit`
for the top-N lists is server-clamped (default 10, max 500 —
`Settings.graph_max_result_limit`). Ties broken by node `id` for
deterministic, reproducible ordering. Never an error for an unprojected
repository — every count is simply `0`. `projected_at`/`freshness` are
included here rather than via a dedicated endpoint (§11).

Computed as four small aggregate Cypher queries in one managed transaction
(node counts by label, relationship counts by type, in-degree top-N,
out-degree top-N) — never one query per node.

## 9. Insights

`GET .../graph/insights` — narrow, explainable, no scoring heuristics;
every value is a plain count or a plain graph fact, never an AI
recommendation:

- **`most_connected_files`**: top-N files by **IMPORTS-only** degree
  (in+out combined), zero-degree files excluded — "which files sit at the
  center of the import graph."
- **`dependency_hotspots`**: top-N symbols by **CALLS+INHERITS-only**
  degree (in+out combined), zero-degree symbols excluded — "which symbols
  are most entangled with the rest of the codebase."
- **`isolated_nodes`**: files with zero IMPORTS-degree, and symbols with
  zero CALLS+INHERITS-degree — deliberately excluding the always-present
  structural CONTAINS/DEFINES kinds (every file has a CONTAINS edge from
  its repository, every symbol a DEFINES edge from its file; counting those
  would make "isolated" nearly meaningless). Capped at `limit` (default
  20).
- **`mutual_import_pairs`** (the circular-dependency indicator): **direct,
  1-hop A↔B mutual IMPORTS only** — file A imports file B *and* file B
  imports file A, deduplicated (`a.id < b.id`). This is a deliberately
  narrow, cheap check (a single aggregate query), **not general cycle
  detection** (`A→B→C→A`). A real, longer cycle is not reported by this
  field. This narrower scope was a deliberate Phase 6 design choice
  ("do not add unnecessary graph algorithms yet"), not an oversight.
- **`unresolved_dependency_count`**: read directly from Phase 4's
  PostgreSQL data via the existing paginated `DependencyEdgeRepository.get_edges(resolution_status=UNRESOLVED)`
  loop (`GraphIntelligenceService._count_unresolved_edges`, the same
  pattern `GraphService._load_all_edges` already established in Phase 5) —
  **never recomputed**, since Neo4j deliberately never projects
  AMBIGUOUS/UNRESOLVED edges at all (Phase 5's own design). This is the one
  `GraphInsights` field with no Neo4j equivalent to derive it from.

`limit` applies independently to each of `most_connected_files`,
`dependency_hotspots`, and `isolated_nodes`; `mutual_import_pairs` is
capped by the same `limit` value applied to its own query.

## 10. API design

New router, `api/graph_intelligence.py`, same prefix as `api/graph.py`
(`/projects/{project_id}/repositories/{repository_id}`), registered
separately in `core/app_factory.py`:

```
GET  .../graph/nodes/{node_id}/dependencies  ?kind=&limit=
GET  .../graph/nodes/{node_id}/dependents    ?kind=&limit=
GET  .../graph/nodes/{node_id}/impact        ?direction=&depth=&kind=&limit=
GET  .../graph/path                          ?source_id=&target_id=&depth=&kind=
GET  .../graph/statistics                    ?limit=
GET  .../graph/insights                      ?limit=
```

`dependencies`/`dependents` are two separate, unambiguous routes (matching
Capability 1/2's own worked examples) rather than one route with a
direction flag whose default could be misread. `impact` keeps a single
route with a `direction` param (default `upstream`) since it's one
capability with a toggle, not two distinct nouns. There is no endpoint that
accepts client-supplied Cypher.

**Validation split, deliberately asymmetric:**
- The **floor** of `depth`/`limit` comes from FastAPI's own `Query(ge=1)` —
  automatic 422 on violation, evaluated before any handler code runs.
- The **ceiling** is checked manually inside each route handler
  (`_check_depth`/`_check_limit` in `api/graph_intelligence.py`) against
  the *injected* `Settings` object, raising the existing `ValidationError`
  (→ 400) — because a `Query(le=...)` bound is evaluated once at import
  time and cannot read a per-request `Depends(get_settings)` value, and
  Phase 6's ceilings needed to stay configurable via `Settings`, not
  hardcoded into route signatures.
- `direction`/`kind` are typed as the domain enums (`DependencyDirection`,
  `GraphRelationshipKind`) — FastAPI/Pydantic rejects invalid values before
  any Cypher-building code ever runs.

**Zero new domain error types.** Every Phase 6 error case maps to one
Phase 3/4/5 already defines:

| Condition | Error | HTTP |
|---|---|---|
| Repository doesn't exist | `NotFoundError` | 404 |
| Node doesn't exist (or belongs to a different repository — indistinguishable) | `NotFoundError` | 404 |
| `source_id`/`target_id` doesn't exist for a path query | `NotFoundError` | 404 |
| `depth`/`limit` below its floor | (FastAPI validation) | 422 |
| `depth`/`limit` above its configured ceiling | `ValidationError` | 400 |
| Neo4j unreachable or a query exceeds its timeout | `GraphUnavailableError` | 503 |
| Repository exists but nothing projected yet | *(not an error)* | 200, all-zero/empty |
| Two nodes exist but no path connects them | *(not an error)* | 200, `found=False` |

## 11. Graph freshness

Two small, purely additive touches make freshness detectable, both flagged
and approved before implementation:

1. **`Neo4jGraphRepository.project_repository`** (Phase 5 file) now stamps
   a `projected_at` property (a native Neo4j `datetime`, computed once and
   reused for both the write and the returned `ProjectionResult`) onto the
   `:Repository` node at the end of every successful projection.
2. **`ParsedFileRepository.get_last_parsed_at(repository_id) -> datetime | None`**
   (Phase 3 port, additive) exposes the already-stored
   `parsed_files.parsed_at` column — no schema change, purely a new read
   path onto data that already existed.

`GraphIntelligenceService.get_statistics` is the only layer with access to
both values, so freshness classification happens there, on every call, from
scratch (no caching, no background job):

- **`"not_projected"`** — `projected_at` is `None`.
- **`"stale"`** — `last_parsed_at > projected_at` (strictly greater).
- **`"fresh"`** — otherwise.

`Neo4jGraphIntelligenceRepository._get_statistics_tx` itself has no
PostgreSQL access and returns only a placeholder freshness
(`"not_projected"` vs. `"fresh"`); `GraphIntelligenceService.get_statistics`
always overwrites it with the correctly-classified value via
`dataclasses.replace` before returning to a caller. Verified directly:
`test_statistics_freshness_reflects_a_real_reparse` deletes a real file
from a real workspace, re-parses (freshness → `stale`), then
re-analyzes+re-projects (freshness → `fresh` again) against the real
pipeline.

**Disclosed limitation, not a hidden gap**: this only detects staleness
from a Phase 3 re-parse (which already cascades away Phase 4 data, so
re-analysis is implied regardless). It does **not** detect
"re-analyzed-without-re-parsing" staleness, because Phase 4 persists no
`analyzed_at` timestamp anywhere in PostgreSQL, and adding one would be a
genuine Phase 4 schema change — exactly what the governing brief says to
avoid unless a concrete Phase 6 requirement proves it necessary. Full
coverage (a Phase 4 `analyzed_at` column) is named as explicit future work
in §16, not built now.

No event system, no background jobs, no push notification of staleness —
a pure, on-demand, read-time comparison recomputed on every
`GET .../graph/statistics` call, deliberately matching "do not implement a
complex event system yet."

## 12. Traversal limits and performance

- Every traversal is bounded: `max_depth` server-clamped (impact 1–10,
  default 3; path 1–15, default 6 — `Settings.graph_max_impact_depth`/
  `graph_max_path_depth`), `limit` server-clamped (default 100, max 500 —
  `Settings.graph_default_result_limit`/`graph_max_result_limit`). There is
  no unbounded `[*]`/`[*..]` pattern anywhere in Phase 6.
- Impact analysis uses `apoc.path.expandConfig` with `bfs: true,
  uniqueness: 'NODE_GLOBAL'` specifically to avoid the exponential
  path-enumeration blowup a plain variable-length `MATCH` would produce for
  a hub node (§6) — the concrete resolution of "avoid unbounded
  variable-length traversals" / "do not create Cypher queries capable of
  accidentally traversing an entire huge repository without limits."
- Every relationship-type set inside a traversal pattern is restricted to a
  fixed, internal list (`CALLS|IMPORTS|INHERITS` by default), pruning the
  search space versus an unrestricted `[*1..N]`.
- Every query is scoped by the same `repository_id` property/index Phase 5
  already relies on — never scans outside the target repository.
- Statistics/insights aggregate queries are O(repository size) — the same
  order of magnitude Phase 5's own bulk `GET .../graph/nodes` already
  accepts, not a new performance risk class.
- No N+1: each capability issues a small, fixed number of Cypher queries
  per HTTP request (1–5), never one query per result row.
- `Settings.graph_query_timeout_seconds` (default 10.0) bounds every
  `Neo4jGraphIntelligenceRepository` public method via
  `asyncio.wait_for(...)` around the whole `execute_read(...)` call — not
  via `neo4j.Query(text, timeout=...)`, which was tried first and
  empirically found to raise `ValueError: Query object is only supported
  for session.run` when used inside a managed transaction
  (`execute_read`/`execute_write`, used throughout for the driver's
  automatic retry behavior). A timeout, like an unreachable Neo4j, is
  translated to `GraphUnavailableError` → 503. Verified directly:
  `test_query_timeout_raises_graph_unavailable_error` (a vanishingly small
  timeout must fail) and `test_no_timeout_configured_runs_normally` (`None`
  must run normally), both against real Neo4j.
- Deliberately **not** prematurely optimized: no caching layer, no
  materialized views, no background jobs — every query runs live, matching
  Phase 5's own posture.

## 13. Security and repository isolation

- **No endpoint accepts client-supplied Cypher, ever** — every route maps
  to one fixed, parameterized Cypher template. No user input is ever
  concatenated into a Cypher string as data; the only per-call *text*
  variation is a relationship type or a `max_depth` bound, both sourced
  from this package's own trusted `REL_TYPE` map or a server-validated
  `int` — never raw client-supplied text (§7).
- **Every template is scoped by `repository_id`**, sourced only from the
  URL path.
- **A node from repository A can never produce results for repository
  B.** Impact analysis and path queries both explicitly re-check
  `m.repository_id = $repository_id` on every traversed node in addition to
  validating the starting/endpoint node(s) up front; a `node_id` real in a
  different repository is treated identically to a `node_id` that doesn't
  exist at all — 404, deliberately indistinguishable, matching Phase 5's
  own `get_neighbors` posture. Verified directly:
  `test_cross_repository_isolation_for_intelligence_queries` (real
  pipeline, two independently-imported repositories) and the dedicated
  cross-repository cases in `tests/integration/test_neo4j_graph_intelligence.py`
  for impact/path/statistics/insights individually.
- **Path queries validate both endpoints before traversal begins** — a
  single existence query checks that both `source_id` and `target_id`
  belong to the requested repository; only then does `shortestPath()` run.
- `direction`/`kind` are domain-enum-typed → FastAPI/Pydantic rejects
  invalid values before any Cypher-building code ever sees them.
- Read responses are structured, typed DTOs (`ImpactAnalysisResponse`,
  `DependencyPathResponse`, `GraphStatisticsResponse`,
  `GraphInsightsResponse`, and reused `GraphNeighborResponse`/
  `GraphNodeResponse`/`GraphRelationshipResponse`), never raw Cypher result
  rows.
- **Stable Forge identifiers only — Neo4j's own internal
  `elementId()`/legacy `id()` is never read, stored, compared, or exposed
  anywhere in Phase 6** — the same posture Phase 5 already established.
  Every node/relationship carries its Forge PostgreSQL `id` as a plain
  string property, matched on directly in every `MATCH`/`WHERE`.

## 14. Testing strategy

Same standard as Phases 3–5, no test-only shortcuts:

- **Unit** (`tests/unit/test_graph_intelligence_service.py`, 32 tests):
  real `GraphIntelligenceService` logic against `tests/fakes.py`'s
  `InMemoryGraphRepository`/`InMemoryGraphIntelligenceRepository` — the
  latter a genuine BFS/shortest-path Python reimplementation of the real
  Neo4j semantics (not a stub), covering direction mapping, depth-bucketing,
  impact excludes-self (including the cyclic-return-to-start case), path
  found/not-found/same-node shapes, statistics aggregation and freshness
  (fresh/stale/not_projected, with explicit `timedelta` offsets to avoid a
  timing race), insights isolated-node/mutual-import-pair/unresolved-count
  passthrough logic, empty-graph and unprojected-repository behavior.
- **Integration, real Neo4j** (`tests/integration/test_neo4j_graph_intelligence.py`,
  33 tests): every capability against small, hand-built graphs written
  directly via `Neo4jGraphRepository.project_repository` (mirrors
  `test_neo4j_graph_projection.py`'s own pattern) — direction correctness,
  shortest-depth-with-multiple-paths dedup, cycle exclusion, kind
  filtering, `limit` enforcement, not-found and cross-repository cases for
  every capability, `projected_at` population, and the two dedicated
  query-timeout tests (§12).
- **Integration, API layer, fakes-backed** (`tests/integration/test_graph_intelligence_api.py`,
  20 tests): every route's status code (200/404/422/400/503), including
  `test_neo4j_unavailable_returns_503` (via the fake's `available` flag)
  and cross-repository-node → 404.
- **Real end-to-end** (`tests/integration/test_real_graph_intelligence.py`,
  3 tests, zero mocking): the complete Phase 2→3→4→5→6 pipeline — real ZIP
  import, real `/parse`, real `/analyze-dependencies`, real
  `/graph/project`, real Phase 6 queries — against the actual
  `forge-postgres`/`forge-neo4j` Docker containers. A 9-file Python +
  TypeScript fixture (a short resolved CALLS chain, a resolved INHERITS
  edge, an unresolved `self`/`this`-call, a circular IMPORTS pair, an
  isolated file) drives every one of the 6 capabilities against
  hand-tallied expected counts, plus dedicated cross-repository-isolation
  and freshness-across-a-real-reparse tests.

## 15. Known limitations

Stated explicitly, matching what earlier sections already describe in
context:

- **Static analysis only** (inherited from Phase 4) — impact analysis does
  not model dynamic dispatch, runtime polymorphism, reflection, or
  conditional imports (§6).
- **Freshness detection is partial** — catches "stale after re-parse," not
  "stale after re-analyze-without-re-parse" (§11); full coverage would
  require a new Phase 4 `analyzed_at` column, named as future work (§16).
- **The circular-dependency insight is a narrow, direct-pair (A↔B) check,
  not general cycle detection** (§9) — a real `A→B→C→A` cycle is not
  reported by `mutual_import_pairs`.
- **An impacted node's reported relationship kind is representative**, from
  whichever path produced its minimum depth, not exhaustive when multiple
  paths/kinds tie at that depth (§6).
- **Dependencies/dependents (Capability 1) include structural
  CONTAINS/DEFINES edges by default** unless a caller passes `kind=` (§5)
  — a documented behavioral detail, not a bug, but easy to miss if a
  caller expects only "real" code-dependency neighbors.
- **No caching** — every query is live; deliberately not addressed now per
  "do not prematurely optimize" (§12).
- **No incremental graph algorithms beyond what's described here** — no
  general cycle detection, no centrality/PageRank-style ranking, no
  community detection — deliberately excluded per "do not add unnecessary
  graph algorithms yet."
- **Single-instance Neo4j only, no query result caching, no query
  cost/plan inspection surfaced to the API** — inherited, unaddressed
  characteristics of Phase 5's own infrastructure, not new Phase 6 gaps.

## 16. Future extension points

- **Full freshness coverage**: a Phase 4 `analyzed_at` timestamp column
  (mirroring `parsed_files.parsed_at`) would let `GraphIntelligenceService.get_statistics`
  also detect "re-analyzed without re-parsing" staleness — a small, additive
  Phase 4 schema change, deliberately not made now (§11/§15).
- **General cycle detection**: `mutual_import_pairs`' narrow direct-pair
  check could be generalized to full cycle detection (e.g. via
  `apoc.nodes.cycles` or a dedicated SCC computation) as a new, explicitly
  separate insights field — not a change to the existing field's
  semantics, to avoid silently changing what already-shipped clients
  receive.
- **Exhaustive multi-path impact reporting**: today each impacted node
  reports one representative relationship kind at its minimum depth (§6);
  a future extension could report all kinds/paths that reach a node at
  that depth, as an additive field, not a breaking change to the existing
  one.
- **Result caching**: once query volume justifies it, a short-lived cache
  keyed by `(repository_id, capability, params)` could sit in front of
  `Neo4jGraphIntelligenceRepository` without changing the port's contract
  — explicitly deferred per "do not prematurely optimize."
- **Automatic staleness surfacing beyond `/statistics`**: e.g. a
  `freshness` field on every Phase 6 response, not only `/statistics` —
  possible, but not built now to keep response shapes minimal and the
  vertical slice's blast radius small.
- **AI-generated explanations/recommendations**: explicitly out of scope
  for this phase and named here only to make clear it was a deliberate
  exclusion (per the governing Phase 6 brief), not an oversight — a future
  phase could layer natural-language explanation on top of these
  deterministic queries without changing anything in this phase.
