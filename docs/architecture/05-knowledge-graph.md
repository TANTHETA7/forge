# Phase 5 — Knowledge Graph / Neo4j

This document describes the Phase 5 implementation as it actually exists in
the codebase. It does not describe aspirational or future behavior; where a
capability is deliberately not implemented, it is called out under "Known
limitations" rather than implied elsewhere.

## 1. Purpose

Phases 3 and 4 build a rich, relational picture of a repository in
PostgreSQL: normalized files/symbols/imports (Phase 3) and resolved
File→File/Symbol→Symbol dependency relationships (Phase 4). That picture is
queryable via SQL/the REST API, but graph-shaped questions — "what are this
function's direct callers", "what does this file transitively import",
"show me everything connected to this symbol" — are exactly what a
relational store is the wrong tool for.

Phase 5 projects Phase 3/4's already-resolved PostgreSQL data into Neo4j as
an explicit graph: nodes for repositories/files/symbols, relationships for
containment, definition, imports, calls, and inheritance. It performs **no
new resolution** — every relationship Phase 5 draws already exists as a
`RESOLVED` `DependencyEdge` row (or a purely structural fact — a file
belongs to a repository, a symbol is defined in a file) before Phase 5 ever
runs. Phase 5 is a projection, not a second analysis pass.

## 2. Architecture

```
api/graph.py
      │  thin — no Cypher, no driver code
      ▼
application/graph/service.py          GraphService
      │  orchestration; reuses ParsedFileRepository (Phase 3) and
      │  DependencyEdgeRepository (Phase 4) — no new Postgres reads beyond
      │  what those ports already expose (get_files, get_edges)
      ▼
domain/graph/{entities,ports}.py
      │  GraphNode, GraphRelationship, GraphNeighbor, ProjectionResult
      │  GraphRepository (port) — ONE Protocol, combining projection
      │  (write) and query (read) methods
      ▼
infrastructure/graph/*.py             neo4j_driver.py (connection lifecycle,
      │                                constraints, health check),
      │                                graph_mapping.py (pure Postgres-entity
      │                                -> graph-entity mapping),
      │                                neo4j_graph_repository.py (the one
      │                                GraphRepository implementation — all
      │                                Cypher lives here),
      │                                dependencies.py (FastAPI DI wiring)
      ▼
Neo4j (bolt://localhost:7687)
```

This mirrors the layering every earlier phase already established:
`domain` has zero framework/driver imports; `application` depends only on
ports; `infrastructure` is the only layer that imports the `neo4j` package
or constructs Cypher; `api` is thin HTTP translation.

**One port, `GraphRepository`**, combining write (`project_repository`) and
read (`get_nodes`/`get_relationships`/`get_neighbors`) methods in a single
`Protocol` — deliberately mirroring `ParsedFileRepository`'s and
`DependencyEdgeRepository`'s own shape (both already mix `save_*`/`get_*` in
one interface) rather than inventing a new write/read split Forge doesn't
use anywhere else. `Neo4jGraphRepository` is its one concrete implementation.

**One application service, `GraphService`**, covering both projection and
queries — mirrors `DependencyAnalysisService`'s own shape exactly (one
service, one write method, several read methods), not two services.

**Mapping is a pure function, not a method on the service or the
repository.** `infrastructure/graph/graph_mapping.py::map_repository_graph`
takes already-loaded `Repository`/`ParsedFile`/`DependencyEdge` values and
returns `GraphNode`/`GraphRelationship` tuples — no I/O, no Cypher, no
`neo4j` import. It is unit-tested with zero infrastructure, the same
"resolvers are pure computation over already-loaded data" pattern Phase 4's
`SymbolDependencyResolver` already established.

## 3. PostgreSQL vs. Neo4j responsibilities

**PostgreSQL remains the sole source of truth**, unchanged by this phase.
Every fact Neo4j holds — a file's path, a symbol's name, an edge's
resolution — already exists in Postgres first; Phase 5 only ever *reads*
Postgres (via Phase 3's `ParsedFileRepository` and Phase 4's
`DependencyEdgeRepository`, both completely unmodified) and *writes* Neo4j.
There is no code path that writes to Postgres from Neo4j, and no code path
that treats Neo4j as authoritative for anything.

**Neo4j is a derived, rebuildable projection.** If the `forge-neo4j`
container's volume were deleted entirely, every repository's graph is
reconstructible by re-running `POST .../graph/project` — nothing is lost,
because nothing was ever created in Neo4j first. This is verified directly:
`test_rebuild_removes_stale_graph_data_after_reparse` and
`test_reprojection_is_idempotent` (`tests/integration/test_real_graph_projection.py`)
both project a repository, mutate the underlying Postgres state (or
re-project unchanged), and confirm Neo4j always ends up exactly matching
current Postgres content — never richer, never staler once re-projected.

## 4. Graph schema

**Node labels** — three, matching Forge's three first-class entities with a
stable id:

| Label | One per | Key properties |
|---|---|---|
| `:Repository` | `Repository.id` | `id`, `repository_id` (equals `id`), `project_id`, `display_name` |
| `:File` | `ParsedFile.id` | `id`, `repository_id`, `path`, `language`, `has_syntax_errors` |
| `:Symbol` | `Symbol.id` | `id`, `repository_id`, `file_id`, `kind` (`function`/`class`/`method`), `name`, `qualified_name`, `parent_symbol_id`, `start_line`, `end_line` |

`Symbol.kind` (function/class/method) is a **property**, not a separate
Neo4j label — a direct instruction from the Phase 5 brief, and a direct
mirror of Phase 3's own `Symbol` dataclass, which already collapsed the
same three kinds into one entity rather than three classes.

**Not modeled as nodes**: `Parameter` (display-only detail, not needed
graph-queryable), `Import` the raw statement (fully represented once
resolved — as the `IMPORTS` relationship it produces, not a node of its
own), `ParseError` (not a structural fact about the codebase).

**Relationship types**:

| Type | Direction | Source |
|---|---|---|
| `CONTAINS` | `Repository`→`File`; also `Symbol`(CLASS)→`Symbol`(METHOD) | Structural — `ParsedFile.repository_id`; `Symbol.parent_symbol_id` |
| `DEFINES` | `File`→`Symbol` | Structural — which file a symbol was parsed from |
| `IMPORTS` | `File`→`File` | Phase 4 `DependencyEdge(kind=IMPORTS, status=RESOLVED)` |
| `CALLS` | `Symbol`→`Symbol` | Phase 4 `DependencyEdge(kind=CALLS, status=RESOLVED)` |
| `INHERITS` | `Symbol`→`Symbol` | Phase 4 `DependencyEdge(kind=INHERITS, status=RESOLVED)` |

Every node and relationship carries `repository_id` as a property (§8), and
every IMPORTS/CALLS/INHERITS relationship additionally carries
`dependency_edge_id` — the originating Phase 4 `DependencyEdge.id` — so it
is always traceable back to the exact Postgres row it came from.

**`REFERENCES` is deliberately not a relationship type here.** Phase 4
declares `DependencyKind.REFERENCES` in its enum for forward extensibility,
but no resolver in Phase 4 currently produces it (confirmed directly against
`DependencyAnalysisService.analyze_repository`, which only ever builds
IMPORTS/CALLS/INHERITS edges). There is no source data to project; adding a
`REFERENCES` relationship type now would be exactly the "blindly implement
every relationship" the Phase 5 brief warns against.

**The `Symbol`-CONTAINS→`Symbol` (class→method) relationship** goes one step
beyond the brief's literal relationship sketch, but is included because it
is directly, reliably derivable — `Symbol.parent_symbol_id` already exists,
no resolution is needed — and was explicitly foreshadowed by Phase 3's own
`Symbol` docstring ("a `Symbol` with `kind=METHOD` and `parent_symbol_id`
pointing at its containing class *is* the nesting relationship later phases
need... captured now, without building any graph traversal on top of it
yet"). Phase 5 is that later phase.

**AMBIGUOUS/UNRESOLVED `DependencyEdge`s are never projected as
relationships.** A Neo4j relationship needs two real endpoint nodes, and an
edge that isn't RESOLVED has a `None` target by construction (Phase 4's own
resolution model — see `docs/architecture/04-dependency-analysis.md`,
"Resolved / Ambiguous / Unresolved"). Such edges remain queryable exactly
where they already are, Phase 4's own `GET .../dependencies` endpoint; Phase
5 does not duplicate them into a placeholder/dangling graph node.

## 5. Node identity

Every Neo4j node's `id` property is Forge's existing PostgreSQL id for the
underlying entity — `Repository.id`, `ParsedFile.id`, `Symbol.id` — sent to
Neo4j as a plain string (the Bolt protocol has no native UUID type) and
parsed back with `UUID(...)` on every read. **Neo4j's own internal
`elementId()`/legacy `id()` is never read, stored, compared, or exposed
anywhere in Forge** — not in the domain entities, not in the API responses,
not in any Cypher template's `WHERE`/`MERGE` clause. Every `MATCH`/`MERGE`
in `neo4j_graph_repository.py` matches on the `id` **property**.

Both `File.id` and `Symbol.id` are themselves `uuid5`s that already fold
`repository_id` into their hash input (Phase 3's own scheme —
`infrastructure/parsing/treesitter_support.py`), so two different
repositories' files/symbols cannot produce colliding ids even before
considering the `repository_id` property — a `(repository_id, id)`
composite uniqueness key would be redundant, not more correct. `Repository.id`
is a plain, already-globally-unique `uuid4()`.

This is also what makes projection idempotent at the id level: re-parsing
unchanged source reproduces identical `Symbol`/`ParsedFile` ids (Phase 3's
own guarantee), so re-projecting reproduces an identical Neo4j node id for
the same logical entity, every time.

## 6. Constraints and indexes

```cypher
CREATE CONSTRAINT repository_id_unique IF NOT EXISTS FOR (r:Repository) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT file_id_unique       IF NOT EXISTS FOR (f:File)       REQUIRE f.id IS UNIQUE;
CREATE CONSTRAINT symbol_id_unique     IF NOT EXISTS FOR (s:Symbol)     REQUIRE s.id IS UNIQUE;

CREATE INDEX file_repository_id   IF NOT EXISTS FOR (f:File)   ON (f.repository_id);
CREATE INDEX symbol_repository_id IF NOT EXISTS FOR (s:Symbol) ON (s.repository_id);
CREATE INDEX symbol_kind          IF NOT EXISTS FOR (s:Symbol) ON (s.kind);
```

Applied idempotently (`IF NOT EXISTS`) by
`infrastructure/graph/neo4j_driver.py::ensure_constraints`, called lazily on
first use — not at application startup — exactly mirroring
`infrastructure/persistence/database.py::ensure_schema`'s own reasoning:
Phase 1–4 (and Phase 5 itself, when Neo4j isn't running) must keep working
with no Neo4j available at all. This is proven directly: the entire Phase
1–4 test suite passes unchanged with zero Neo4j dependency.

## 7. Relationship mapping (how a Postgres row becomes a graph edge)

`infrastructure/graph/graph_mapping.py::map_repository_graph` takes one
repository's already-loaded `ParsedFile`s (with their `Symbol`s) and
`DependencyEdge`s and returns the complete node/relationship set:

1. One `:Repository` node.
2. One `:File` node per `ParsedFile`, plus a `CONTAINS` relationship from
   the repository.
3. One `:Symbol` node per `Symbol` in every file, plus a `DEFINES`
   relationship from its file, plus (for a `METHOD` with a
   `parent_symbol_id`) a `CONTAINS` relationship from its containing class.
4. For each `DependencyEdge`: if `resolution_status` is `RESOLVED` and its
   kind is `IMPORTS`/`CALLS`/`INHERITS`, one relationship connecting the
   right two node ids (`source_file_id`/`target_file_id` for IMPORTS;
   `source_symbol_id`/`target_symbol_id` for CALLS/INHERITS). Anything else
   (AMBIGUOUS, UNRESOLVED, or a kind with no graph-relationship mapping)
   produces nothing.

This function is pure — no database access — and is exhaustively
unit-tested in `tests/unit/test_graph_mapping.py` against hand-built
`ParsedFile`/`Symbol`/`DependencyEdge` values, independent of any real
Postgres or Neo4j.

## 8. Repository isolation

A graph must never mix data between repositories — enforced structurally,
not by convention:

- **Every node and relationship carries a `repository_id` property**,
  including `:Symbol`/`:File` nodes that are already reachable from
  `:Repository` via a relationship — this is deliberate redundancy: it lets
  every Cypher template filter directly on the node/relationship itself
  (`WHERE n.repository_id = $repository_id`) rather than requiring a graph
  traversal just to enforce isolation.
- **Every Cypher template in `neo4j_graph_repository.py` binds
  `repository_id` as a query parameter sourced only from the URL path** —
  never from a request body or query string a client could use to target a
  different repository's data.
- **The delete step of a rebuild is scoped by `repository_id`**
  (`MATCH (n {repository_id: $repository_id}) DETACH DELETE n`) — never a
  blanket `MATCH (n) DETACH DELETE n`, which would wipe every repository's
  graph at once.
- **`get_neighbors` re-checks the found node's own `repository_id`** before
  returning anything — a `node_id` that is real but belongs to a *different*
  repository is treated identically to a `node_id` that doesn't exist at
  all (§10).

Verified directly by `test_two_repositories_never_cross_contaminate`
(`tests/integration/test_neo4j_graph_projection.py`) and
`test_repository_isolation_across_two_projected_repositories`
(`tests/integration/test_real_graph_projection.py`) — the second projects
two real, independently-imported/parsed/analyzed repositories into the same
Neo4j instance and confirms zero overlap in returned node ids, and that
re-projecting one never changes the other's node set.

## 9. Projection lifecycle and idempotency

Projection is **pull-based and on-demand**, triggered only by an explicit
`POST .../graph/project` call — matching the explicit-pipeline-stage
precedent already established between import→parse→analyze. It is never
automatic or event-driven: re-parsing or re-analyzing a repository does
**not** itself trigger a re-projection.

`GraphService.project_repository`:
1. Loads the `Repository`, requires `READY`.
2. Loads `ParsedFile`s via `ParsedFileRepository.get_files`; requires
   non-empty (the repository must have been parsed).
3. Loads all `DependencyEdge`s via `DependencyEdgeRepository.get_edges`,
   paginating internally until exhausted (`_load_all_edges`) — may
   legitimately be empty (parsed but never analyzed), which is not an
   error; the projected graph just has no IMPORTS/CALLS/INHERITS
   relationships yet.
4. Checks `GraphRepository.is_available()` — fails fast with
   `GraphUnavailableError` before attempting any write if Neo4j isn't
   reachable (§11).
5. Maps to `GraphNode`/`GraphRelationship` (§7) and calls
   `GraphRepository.project_repository`.

`Neo4jGraphRepository.project_repository` runs as **two managed
transactions**:
- **Cleanup**: `MATCH (n {repository_id: $repository_id}) DETACH DELETE n`
  — removes every previously-projected node (and, via `DETACH`, every
  relationship touching one) for this repository only.
- **Rebuild**: batched `UNWIND $rows AS row MERGE (x:Label {id: row.id}) SET x += row`
  per node label, then the equivalent `UNWIND`+`MATCH`+`MERGE` pattern per
  relationship type, matching endpoints by `id` (and, for IMPORTS/CALLS/
  INHERITS, keying the `MERGE` on `dependency_edge_id` too — see §12 for
  why).

**Full rebuild only — no incremental/diff-based projection in this phase.**
`POST .../graph/project` always recomputes the entire graph for that
repository; there is no separate "rebuild" endpoint distinct from
"project" — projecting *is* rebuilding, every time. This is the minimum bar
the Phase 5 brief asks for ("at minimum implement a safe full
projection/rebuild operation") and mirrors Phase 3/4's own precedent
(neither ever built incremental persistence either).

**Idempotency** comes from two things working together: `MERGE` (not plain
`CREATE`) within the rebuild step, and delete-before-rebuild at the
repository level. `MERGE` alone would handle *creation* idempotently but not
*removal* — if a symbol is deleted on re-parse, a MERGE-only strategy would
leave its stale node behind forever. Delete-then-rebuild is what actually
guarantees the graph exactly reflects current Postgres state after every
run, matching Phase 3/4's own "replace on rerun" persistence pattern
exactly. Verified directly: running projection twice with unchanged
Postgres data produces an identical node/relationship id set
(`test_reprojection_is_idempotent`, both the focused
`test_reprojection_is_idempotent_not_duplicating` unit-level test and the
full real-pipeline version).

## 10. Rebuild strategy and consistency across the pipeline

Walking the full lifecycle the brief asks about:

1. **Import** (Phase 2) — no graph exists yet.
2. **Parse** (Phase 3) — no graph exists yet.
3. **Analyze dependencies** (Phase 4) — no graph exists yet.
4. **Project** — the graph is created for the first time, exactly reflecting
   current Postgres state (§9).
5. **Re-parse** (Phase 3) — Postgres's `parsed_files`/`symbols` are replaced
   (cascading away Phase 4's `dependency_edges` too, per Phase 4's own
   documented cascade). **The existing Neo4j graph is now stale.** Phase 5
   does not auto-detect or auto-react to this — no hidden side effect is
   wired into `ParsingService` — consistent with "don't redesign Phase 1–4"
   and the explicit-stage precedent already established between Phase 2 and
   Phase 3 (re-parsing already requires an explicit re-`/analyze-dependencies`
   call; it now additionally implies an explicit re-`/graph/project` call).
6. **Re-analyze dependencies** (Phase 4) — same story specifically for
   IMPORTS/CALLS/INHERITS relationships.
7. **Project again** — the delete+rebuild strategy (§9) naturally produces a
   graph that exactly matches current Postgres state: zero duplication (old
   data for this repository was fully deleted first), zero staleness
   (nothing carried over). Verified directly against a real re-parse:
   `test_rebuild_removes_stale_graph_data_after_reparse` deletes a real file
   from a repository's real workspace on disk, re-parses, re-analyzes,
   re-projects, and confirms the corresponding `:File` node and its
   `INHERITS` relationship are gone from Neo4j while untouched files/
   relationships survive.

## 11. Failure handling

- **Neo4j unreachable at projection time**: `GraphService` calls
  `GraphRepository.is_available()` before attempting any write, and raises
  `GraphUnavailableError` (a new, purely additive `domain/errors.py` type)
  with a clear message rather than letting a raw driver exception surface.
  Mapped to **HTTP 503** in `api/error_handlers.py`.
- **Neo4j drops mid-operation**: every method on `Neo4jGraphRepository`
  wraps its `execute_write`/`execute_read` call in a `try`/`except`
  catching `neo4j.exceptions.ServiceUnavailable`/`AuthError`/`SessionExpired`
  and re-raises as `GraphUnavailableError` — a raw driver exception never
  crosses out of `infrastructure/graph/`.
- **Partial projection failure**: if the rebuild transaction fails after the
  cleanup transaction already committed, the repository's graph is left
  **empty** for that repository, not partially-stale — surfaced to the
  caller as a failed `POST .../graph/project` (503/500). The caller is
  expected to retry the whole call. An empty, trivially-re-projectable graph
  is consistent with "Neo4j is derived, never canonical"; a half-old/
  half-new graph would not be.
- **Nonexistent repository**: `NotFoundError` → 404, on every route.
- **Repository not `READY` or not yet parsed**: `UnsupportedRepositoryStateError`
  → 409, reused verbatim from Phase 3/4 — no new error type needed.
- **Repository with no dependencies** (parsed but never analyzed, or
  analyzed with nothing resolvable): never an error — the graph just has no
  IMPORTS/CALLS/INHERITS relationships; `GET .../graph/nodes` and
  `GET .../graph/dependencies` return whatever exists (possibly `[]`), not a
  4xx.
- **Repository with no graph projected yet**: never an error — `GET`
  routes only require the repository to *exist* (404 otherwise), matching
  Phase 4's own looser read-precondition (verified: Phase 4's `get_edges`/
  `get_edge` only call `_require_repository`, never require analysis to
  have run).
- **A single resolver/mapping bug**: cannot happen mid-projection in a way
  that partially corrupts data, because mapping (§7) is pure, in-memory, and
  runs to completion (or raises) entirely before any Neo4j write begins —
  there is no per-edge try/except inside the projection write path the way
  Phase 4 has per-edge exception isolation, because there is nothing left to
  resolve by the time Phase 5 runs; a mapping bug is a Phase 5 code defect,
  not an expected-and-handled runtime condition the way an unresolvable
  import is.

## 12. Security

- **No endpoint accepts client-supplied Cypher, ever.** Every one of the 4
  `api/graph.py` routes maps to exactly one predetermined, parameterized
  Cypher template inside `neo4j_graph_repository.py`. No user input is ever
  concatenated into a Cypher string — every value (`repository_id`,
  `node_id`, filter values) is passed as a driver query parameter, the same
  posture as SQLAlchemy's own parameter binding already used throughout
  Phase 2–4.
- The only per-call variation in a Cypher template's *text* is a node label
  or relationship type — selected from `neo4j_graph_repository.py`'s own
  internal, fixed `_NODE_LABEL`/`_REL_TYPE` maps, keyed by the
  `GraphNodeKind`/`GraphRelationshipKind` enum (validated/coerced by FastAPI
  before ever reaching this layer) — never a raw client-supplied string.
  This is the same class of safe-identifier-interpolation SQLAlchemy itself
  uses internally for table/column names, not string-built query data.
- **Read responses are structured and typed**
  (`GraphNodeResponse`/`GraphRelationshipResponse`/`GraphNeighborResponse`),
  never raw Cypher result rows — matching the brief's "prefer useful graph
  queries over exposing arbitrary Cypher execution."
- Two distinct relationship kinds are keyed differently in `MERGE` on
  purpose: IMPORTS/CALLS/INHERITS include `dependency_edge_id` in the merge
  key (so two distinct Postgres edges between the same two nodes — e.g. two
  separate `from x import a` / `from x import b` statements resolving to
  the same file pair — become two distinct, individually-traceable
  relationships, never silently collapsed into one with lost provenance);
  CONTAINS/DEFINES don't need this (`dependency_edge_id` is always `None`
  for them, and they're structurally unique per (source, target) pair
  already).

## 13. Repository isolation and cross-repository query attempts

Covered in depth in §8; the specific "cross-repository query attempt"
case: `GET .../graph/neighbors/{node_id}` re-validates that `node_id`'s own
`repository_id` property matches the path's `repository_id` before
returning any data. A `node_id` that is real but belongs to a different
repository produces exactly the same `404` a nonexistent `node_id` would —
deliberately indistinguishable, so a client probing for other repositories'
node ids learns nothing from the response. Verified directly:
`test_get_neighbors_returns_none_for_cross_repository_node` (real Neo4j) and
`test_get_neighbors_cross_repository_node_returns_404` (fakes-backed API
test) and `test_repository_isolation_across_two_projected_repositories`
(the full real pipeline).

## 14. Query model

```
POST /api/v1/projects/{project_id}/repositories/{repository_id}/graph/project
GET  /api/v1/projects/{project_id}/repositories/{repository_id}/graph/nodes
GET  /api/v1/projects/{project_id}/repositories/{repository_id}/graph/dependencies
GET  /api/v1/projects/{project_id}/repositories/{repository_id}/graph/neighbors/{node_id}
```

- `POST .../graph/project` — full projection/rebuild (§9). Returns
  `{repository_id, node_count, relationship_count, projected_at}`. `201`.
- `GET .../graph/nodes` — nodes for the repository, filterable by `kind`
  (`repository`/`file`/`symbol`), paginated (`limit`/`offset`).
- `GET .../graph/dependencies` — IMPORTS/CALLS/INHERITS (and structural
  CONTAINS/DEFINES) relationships, filterable by `kind`, paginated. Each
  entry includes `source_id`, `target_id`, `kind`, `repository_id`,
  `dependency_edge_id` (`None` for structural relationships), and
  `properties`.
- `GET .../graph/neighbors/{node_id}` — one node's direct neighbors,
  `direction=incoming|outgoing|both` (default `both`), paginated. Each
  entry includes the neighboring node, the connecting relationship's kind,
  and whether it was outgoing or incoming relative to `node_id`.

`api/graph.py` constructs its own `Neo4jGraphRepository` (via
`infrastructure/graph/dependencies.py::get_graph_repository`) and reuses the
existing Postgres-backed `RepositoryRepository`/`ParsedFileRepository`/
`DependencyEdgeRepository` providers from
`infrastructure/persistence/dependencies.py` — no new Postgres wiring.

## 15. Known limitations

Stated explicitly, matching what earlier sections already describe in
context:

- **No incremental projection.** Every `POST .../graph/project` call is a
  full delete+rebuild for that repository (§9) — deliberately out of scope
  per the brief's own "at minimum, safe full rebuild" bar.
- **Staleness is caller-managed, not automatic.** Re-parsing or
  re-analyzing a repository does not itself re-trigger graph projection
  (§10) — a consumer must explicitly call `POST .../graph/project` again.
- **AMBIGUOUS/UNRESOLVED dependency edges are never represented in the
  graph** (§4/§7) — queryable only via Phase 4's own `/dependencies`
  endpoint.
- **`REFERENCES` relationships are not built** (§4) — no Phase 4 resolver
  currently produces that data; this is a direct, honest consequence of
  Phase 4's own current scope.
- **The pre-existing `project_id`-not-cross-checked-against-`repository_id`
  characteristic of Phase 2–4's own routers is inherited by Phase 5's new
  routes for consistency**, not silently — every Phase 1–4 route (`get_repository`,
  `/parse`, `/analyze-dependencies`, and their `GET`s) looks up purely by
  `repository_id` in the URL path, never cross-checking it against the
  path's `project_id`; Phase 5's routes do the same, for consistency with
  the rest of the API surface. This does **not** weaken repository
  isolation in the graph itself (§8/§13 are independent, enforced via
  `repository_id`-scoped Cypher regardless of which `project_id` was in the
  URL) — it is a pre-existing characteristic of the whole API, not a Phase
  5-specific or graph-specific gap, and fixing it is out of scope for a
  phase whose brief is "do not modify/redesign Phase 1–4 without a concrete
  Phase 5 requirement."
- **No Neo4j driver shutdown hook** — mirrors Postgres's own current lack of
  one (`infrastructure/persistence/database.py` doesn't dispose its cached
  engine on shutdown either); not a new gap.
- **Single-instance Neo4j only** — no causal-cluster/multi-database routing
  logic. The configured image (`neo4j:5-community`) doesn't support
  clustering anyway, so this isn't a real limitation for the current infra,
  just worth naming for future-extension awareness (§16).
- **Batch `MATCH`-then-`MERGE` relationship writes produce a benign Neo4j
  "Cartesian product" performance notification** for CONTAINS/DEFINES
  batches (visible in test logs) — expected given the query shape (finding
  two arbitrary nodes by id before connecting them, independent of any
  existing path between them), harmless at realistic per-repository batch
  sizes, and not a correctness issue. Not addressed further in this phase.

## 16. Future extension strategy

- **Incremental projection**: once needed, the natural extension is a
  diff-based write (compare current Neo4j state to the new Postgres state,
  `MERGE` only what changed, explicitly `DELETE` only what's gone) rather
  than the current delete-then-rebuild. `GraphRepository.project_repository`'s
  signature would not need to change; only `Neo4jGraphRepository`'s
  internals would.
- **`REFERENCES` relationships**: the moment Phase 4 gains a resolver that
  produces `DependencyKind.REFERENCES` edges, projecting them is a small,
  additive change to `graph_mapping.py`'s `_DEPENDENCY_KIND_TO_GRAPH_KIND`
  map and `GraphRelationshipKind`'s enum — the same code path already
  handles IMPORTS/CALLS/INHERITS identically.
- **New languages**: Phase 3/4 already generalize per-language parsing and
  resolution; Phase 5's mapping and Neo4j layers are entirely
  language-agnostic (they only ever see already-normalized `ParsedFile`/
  `Symbol`/`DependencyEdge` data), so a new language requires zero Phase 5
  changes.
- **Automatic re-projection on re-parse/re-analyze**: if ever desired, this
  would be an explicit, opt-in orchestration change in `application/parsing/service.py`/
  `application/dependency_analysis/service.py` (e.g. an optional callback or
  event), not a Phase 5-internal change — deliberately not built now to
  avoid a hidden side effect and to keep each stage's contract explicit.
- **Health-check integration**: `infrastructure/graph/neo4j_driver.py::ping`
  already exists and is unit-testable; wiring it into the existing
  `GET /health` endpoint (to report Neo4j reachability alongside the
  service's own status) is a small, additive `application/health_service.py`
  change, deliberately not made in this phase to keep the vertical slice's
  blast radius minimal.
- **Multi-repository graph queries** (e.g. "find all callers of this
  function across every repository in a project"): would require a
  deliberate, explicit new query shape (and explicit authorization
  decisions) rather than relaxing the current per-repository isolation
  guarantee — not attempted here.
