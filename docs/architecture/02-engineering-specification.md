# Forge — Engineering Specification v2

> Status: **Blueprint — no implementation yet.** This document specifies everything needed to
> build the Knowledge-Graph-Centric Pipeline architecture agreed in
> [`01-system-architecture.md`](01-system-architecture.md) (Phase 1, complete) and the
> architecture review that followed it. Nothing in Phase 1 changes shape here — this document
> only adds detail for the modules that don't exist yet. Treat every schema, signature, and
> diagram below as the contract implementation must satisfy, not a suggestion.

## Table of contents

1. [Overall project vision](#1-overall-project-vision)
2. [Functional requirements](#2-functional-requirements)
3. [Non-functional requirements](#3-non-functional-requirements)
4. [Module registry](#4-module-registry)
5. [Internal APIs between modules](#5-internal-apis-between-modules)
6. [Data flow diagrams](#6-data-flow-diagrams)
7. [Sequence diagrams](#7-sequence-diagrams)
8. [Class diagrams](#8-class-diagrams)
9. [Database schema (PostgreSQL)](#9-database-schema-postgresql)
10. [Neo4j graph schema](#10-neo4j-graph-schema)
11. [AST schema](#11-ast-schema)
12. [Dependency graph schema](#12-dependency-graph-schema)
13. [Knowledge graph schema (logical)](#13-knowledge-graph-schema-logical)
14. [Folder structure](#14-folder-structure)
15. [File responsibilities](#15-file-responsibilities)
16. [Naming conventions](#16-naming-conventions)
17. [Coding standards](#17-coding-standards)
18. [Error handling strategy](#18-error-handling-strategy)
19. [Logging strategy](#19-logging-strategy)
20. [Testing strategy](#20-testing-strategy)
21. [Security considerations](#21-security-considerations)
22. [Future scalability](#22-future-scalability)
23. [Performance considerations](#23-performance-considerations)
24. [Plugin architecture](#24-plugin-architecture)
25. [AI integration strategy](#25-ai-integration-strategy)
26. [Risks and tradeoffs](#26-risks-and-tradeoffs)

---

## 1. Overall project vision

Forge turns a source repository into a **queryable knowledge graph** and builds every
software-intelligence feature — search, architecture visualization, metrics, git history,
change-impact analysis, generated documentation, and an AI assistant — as a **reader** of that
one graph. A repository is parsed exactly once (and re-parsed only for files that changed since
the last import); every feature after that point consumes structure that already exists rather
than re-deriving it.

The product promise to a user is: *point Forge at a repository, and every question you'd
otherwise answer by grepping, reading commit logs, or manually tracing imports — "what depends
on this function," "who touched this file most," "what breaks if I change this," "explain this
module" — is answered from one consistent, already-computed model of the codebase.*

Design priorities, in order: **correctness of the graph** (wrong edges make every downstream
feature wrong) → **maintainability** (this is a multi-year product with a long module list ahead
of it) → **performance** (large repos must ingest and stay incrementally cheap to update) →
**extensibility** (new languages, new analysis modules, new AI providers must be additive, not
invasive).

---

## 2. Functional requirements

Requirement IDs are stable identifiers for traceability to future tickets/tests — don't renumber
them once implementation starts; append.

### 2.1 Repository Import

| ID | Requirement |
|---|---|
| FR-1.1 | User can register a repository by git URL (public or credentialed) or by uploading an archive. |
| FR-1.2 | System clones/pulls the repository into a working directory and enumerates all tracked files. |
| FR-1.3 | System computes a content hash per file and diffs against the previous import (if any) to determine the changed-file set. |
| FR-1.4 | System records one `ImportJob` per import attempt with status (`pending`, `running`, `succeeded`, `failed`, `partially_failed`) and per-stage progress. |
| FR-1.5 | User can query import job status and receive progress until completion (polling; see §5.2). |
| FR-1.6 | A failed import (e.g., clone failure, disk quota) leaves the previously-ingested graph state untouched — imports are atomic at the job level. |

### 2.2 Parsing / AST / Dependency Graph (the pipeline)

| ID | Requirement |
|---|---|
| FR-2.1 | System detects the language of each changed file (extension + content heuristics for ambiguous extensions). |
| FR-2.2 | System parses each changed file with the language's tree-sitter grammar into a concrete syntax tree. |
| FR-2.3 | System converts each concrete syntax tree into Forge's language-agnostic AST (Module/Class/Function/Symbol/Import/Call). |
| FR-2.4 | System derives dependency edges (imports, calls, inheritance, definition containment) from the AST. |
| FR-2.5 | A file that fails to parse (syntax error, unsupported grammar edge case) is recorded as a per-file failure and excluded from the graph — it must not fail the whole import. |
| FR-2.6 | Unsupported languages are recorded as "skipped — unsupported language" per file, not silently dropped. |

### 2.3 Knowledge Graph

| ID | Requirement |
|---|---|
| FR-3.1 | System upserts nodes and edges for every successfully parsed file into the graph store, keyed so re-ingestion of an unchanged file is a no-op. |
| FR-3.2 | System removes nodes/edges belonging to files deleted from the repository since the last import. |
| FR-3.3 | System computes and persists per-node metrics (see §2.6) as graph properties at ingestion time, not at query time. |
| FR-3.4 | System folds git history (commit → file → author edges) into the same graph as the code-structure edges. |
| FR-3.5 | The graph is queryable by every downstream module exclusively through the read port defined in §5.1 — no downstream module parses source or calls the graph driver directly. |

### 2.4 Search

| ID | Requirement |
|---|---|
| FR-4.1 | User can full-text search symbol names, file paths, and docstrings/comments across an ingested repository. |
| FR-4.2 | Search results rank exact symbol-name matches above fuzzy/substring matches. |
| FR-4.3 | The search index is rebuilt from the knowledge graph after ingestion completes — it is never the source of new facts. |

### 2.5 Architecture views

| ID | Requirement |
|---|---|
| FR-5.1 | User can request a module-level dependency graph for visualization (nodes = modules, edges = import relationships), paginated/filterable for large repos. |
| FR-5.2 | User can drill from a module view into its constituent classes/functions and their call edges. |

### 2.6 Metrics

| ID | Requirement |
|---|---|
| FR-6.1 | System computes, per function/class/file: lines of code, cyclomatic complexity, fan-in, fan-out. |
| FR-6.2 | System computes, per file: churn (commits touching it in a configurable window) by joining code-structure nodes with git-history edges. |
| FR-6.3 | User can request aggregate metrics (e.g., average complexity) over an arbitrary graph subset (a module, a directory) computed at read time from precomputed per-node values — not recomputed from source. |

### 2.7 Git analysis

| ID | Requirement |
|---|---|
| FR-7.1 | User can view commit history and authorship for any file/symbol, sourced from graph history edges. |
| FR-7.2 | User can request "impact of my uncommitted working-tree changes" — the one path permitted to read live git state instead of the graph (see §4, Git Analysis). |

### 2.8 Impact analysis

| ID | Requirement |
|---|---|
| FR-8.1 | Given a symbol or file, user can request its full transitive blast radius (everything that depends on it, to a configurable depth). |
| FR-8.2 | Given an uncommitted working-tree diff, user can request the blast radius of exactly the changed symbols. |

### 2.9 Documentation generation

| ID | Requirement |
|---|---|
| FR-9.1 | User can request a generated narrative summary of a module/class/function, composed from graph structure plus (optionally) AI-generated prose. |

### 2.10 AI assistant

| ID | Requirement |
|---|---|
| FR-10.1 | User can ask a natural-language question about the ingested repository and receive an answer grounded in graph-retrieved context (graph-RAG), not the raw source tree. |
| FR-10.2 | The assistant states when it cannot answer from graph context rather than fabricating an answer from general knowledge. |

### 2.11 Auth (stub scope for this document — full spec is a future phase)

| ID | Requirement |
|---|---|
| FR-11.1 | System issues a JWT on successful login and requires it on every non-health API route. |

---

## 3. Non-functional requirements

| Category | Requirement |
|---|---|
| **Performance** | Full ingestion of a 100k-LOC repository completes in < 5 minutes on a single worker. Incremental re-ingestion of a 10-file commit completes in < 10 seconds. Read-side API endpoints (search, metrics, architecture view) respond in < 500ms p95 for repos up to 500k LOC. |
| **Scalability** | Ingestion pipeline is stateless per job and horizontally scalable by running multiple worker processes once extracted to a queue (§22). Graph store must handle repos up to ~5M LOC without schema changes. |
| **Reliability** | A partial ingestion failure (some files fail to parse) does not fail the whole job (FR-2.5) and does not corrupt previously-ingested graph state (FR-1.6). |
| **Availability** | Read-side API (search, metrics, etc.) remains available while an ingestion job for the *same* repository is running — reads see the last-consistent graph state, not a half-written one (write-then-swap or transactional upsert, not in-place partial writes). |
| **Consistency** | The knowledge graph is eventually consistent with the repository's HEAD, bounded by "ingestion job completed." No downstream module may present stale data as current without a `last_ingested_at` timestamp attached to the response. |
| **Maintainability** | Every module obeys the layer dependency rule (`api → application → domain ← infrastructure`) established in Phase 1; violations caught by import-linter in CI (§17). |
| **Extensibility** | Adding a language, an analysis module, or an AI provider must not require changes to the ingestion pipeline's existing stages or to unrelated consumer modules (§24). |
| **Portability** | Graph store, relational store, and search index are each behind a domain port; swapping implementations must not touch application-layer code (already the stated rule for Search: SQLite FTS → Elasticsearch, extended here to Neo4j and Postgres). |
| **Security** | See §21 in full; headline: no arbitrary code from an ingested repository is ever executed, secrets never enter logs or graph data, auth required on all non-health routes. |
| **Observability** | Every ingestion job and every API request is traceable via a correlation ID from HTTP entry to log line (§19). |
| **Privacy** | v1 AI integration runs against a local model (Ollama) — no repository content leaves the deployment by default (§25). |

---

## 4. Module registry

This is the canonical answer to "for every module: why it exists, who owns it, who consumes it,
inputs, outputs, dependencies." Every later section refers back to this table rather than
repeating it.

| Module | Why it exists | Owner (home package) | Consumers | Inputs | Outputs | Depends on |
|---|---|---|---|---|---|---|
| **Repository Import** | Get source onto disk and know exactly what changed since last time. | `application/ingestion/`, `infrastructure/git/` | Ingestion pipeline (internal) | Git URL or archive upload | `ImportJob`, changed-file list, `FileHash` records | `domain/repository/`, Postgres |
| **Language Detection** | Route each file to the correct parser. | `domain/parsing/` | Ingestion pipeline (internal) | File path + content | `Language` enum | none (pure) |
| **Tree-sitter Parsing** | Turn source text into a syntax tree. | `infrastructure/parsing/` | Ingestion pipeline (internal) | File content + `Language` | Concrete syntax tree | tree-sitter grammar bindings |
| **AST Construction** | Normalize per-language syntax trees into one language-agnostic model every later stage can use. | `domain/parsing/` | Dependency Graph Generation (internal) | Concrete syntax tree | Forge AST (§11) | none (pure) |
| **Dependency Graph Generation** | Derive structure/relationship edges from the AST. | `domain/dependency/` | Knowledge Graph Write (internal) | Forge AST | In-memory `DependencyGraph` (§12) | `domain/parsing/` |
| **Knowledge Graph (write)** | The only writer of the graph; also where metrics get computed once. | `infrastructure/graph/` (implements `KnowledgeGraphWriter`) | Ingestion pipeline (internal) | `DependencyGraph` + git-history edges | Persisted graph (Neo4j) | Neo4j driver, `domain/graph/` |
| **Knowledge Graph (read port)** | The only legal path from any consumer to graph data — enforces "never parse twice." | `domain/graph/ports.py` | Search, Architecture, Metrics, Git Analysis, Impact, Docs, AI | Query parameters (node id, filters, depth) | Typed graph query results | none (interface only) |
| **Search** | Fast text lookup over symbols/paths/docs. | `infrastructure/search/`, `application/search/` | `api/search.py` → frontend | Query string | Ranked `SearchHit[]` | `domain/graph/ports.py` |
| **Architecture views** | Shape graph subsets into visualization payloads. | `application/architecture/` | `api/architecture.py` → frontend (React Flow/Cytoscape) | Repo id, scope (module/file), depth | Nodes/edges payload for the graph UI | `domain/graph/ports.py` |
| **Metrics** | Aggregate precomputed per-node metrics; no recomputation. | `application/metrics/`, `domain/metrics/` (formulas used at ingestion time) | `api/metrics.py` → frontend | Repo id, scope | Aggregate metric values | `domain/graph/ports.py` |
| **Git Analysis** | History/authorship queries; the one narrow live-git exception. | `application/git_analysis/`, `infrastructure/git/` (live-diff only) | `api/git.py` → frontend | Repo id, file/symbol id, OR "live" flag | Commit/author history, or live diff | `domain/graph/ports.py` (+ `infrastructure/git/` for live) |
| **Impact analysis** | Blast-radius traversal for a symbol or a live diff. | `application/impact/` | `api/impact.py` → frontend | Symbol/file id or live diff | Transitive dependents, depth-bounded | `domain/graph/ports.py`, Git Analysis (live-diff path) |
| **Documentation generation** | Compose graph + optional AI prose into a narrative doc. | `application/docs/` | `api/docs.py` → frontend | Repo id, scope | Markdown/structured doc | `domain/graph/ports.py`, `infrastructure/ai/` (optional) |
| **AI assistant** | Answer natural-language questions grounded in the graph. | `application/ai/`, `infrastructure/ai/` | `api/ai.py` → frontend | Natural-language question + repo id | Grounded answer + cited graph nodes | `domain/graph/ports.py`, `infrastructure/ai/` (Ollama) |
| **Auth** | Identify the caller. | `application/auth/`, `infrastructure/auth/` | Every non-health API route (via FastAPI dependency) | Credentials | JWT | Postgres (users) |

---

## 5. Internal APIs between modules

Two distinct API surfaces exist: **internal ports** (Python interfaces, in-process, no
serialization) between backend modules, and the **public HTTP API** the frontend consumes. All
signatures below are interface contracts — no method bodies, per the "blueprint only" instruction.

### 5.1 Core ports (`domain/graph/ports.py`)

```python
class KnowledgeGraphWriter(Protocol):
    """Implemented by infrastructure/graph/neo4j_writer.py. Called only from
    application/ingestion/. No other module may hold a reference to this port."""

    def upsert_file_subgraph(self, file_id: FileId, graph: DependencyGraph) -> None: ...
    def remove_file_subgraph(self, file_id: FileId) -> None: ...
    def write_metrics(self, node_id: NodeId, metrics: NodeMetrics) -> None: ...
    def write_history_edges(self, edges: list[HistoryEdge]) -> None: ...


class GraphStructureReader(Protocol):
    """Structural queries: nodes, edges, containment, imports, calls."""

    def get_node(self, node_id: NodeId) -> GraphNode | None: ...
    def get_neighbors(self, node_id: NodeId, edge_types: list[EdgeType], depth: int) -> Subgraph: ...
    def get_module_graph(self, repo_id: RepoId, scope: str | None) -> Subgraph: ...


class GraphMetricsReader(Protocol):
    """Precomputed metric lookups — never triggers recomputation."""

    def get_node_metrics(self, node_id: NodeId) -> NodeMetrics | None: ...
    def aggregate_metrics(self, node_ids: list[NodeId]) -> AggregateMetrics: ...


class GraphHistoryReader(Protocol):
    """Git-history edges already folded into the graph at ingestion time."""

    def get_commit_history(self, node_id: NodeId, limit: int) -> list[CommitRef]: ...
    def get_churn(self, node_id: NodeId, since: datetime) -> int: ...
```

Rule: an application service depends on exactly the sub-port(s) it needs (ISP, per the
architecture review) — e.g. `application/search/` depends only on `GraphStructureReader`, never
on `GraphMetricsReader`.

### 5.2 Public HTTP API (selected — full OpenAPI spec is generated by FastAPI, not hand-written)

| Method | Path | Module | Request | Response |
|---|---|---|---|---|
| `POST` | `/api/v1/repositories` | Repository Import | `{source: url \| upload}` | `{repo_id, import_job_id}` |
| `GET` | `/api/v1/import-jobs/{id}` | Repository Import | — | `{status, stage, progress, errors[]}` |
| `GET` | `/api/v1/repositories/{id}/search?q=` | Search | — | `SearchHit[]` |
| `GET` | `/api/v1/repositories/{id}/architecture?scope=&depth=` | Architecture | — | `{nodes[], edges[]}` |
| `GET` | `/api/v1/repositories/{id}/metrics?scope=` | Metrics | — | `AggregateMetrics` |
| `GET` | `/api/v1/repositories/{id}/git/history?node=` | Git Analysis | — | `CommitRef[]` |
| `POST` | `/api/v1/repositories/{id}/git/live-diff` | Git Analysis | — | `{changed_symbols[]}` |
| `GET` | `/api/v1/repositories/{id}/impact?node=&depth=` | Impact Analysis | — | `{dependents[]}` |
| `POST` | `/api/v1/repositories/{id}/impact/live` | Impact Analysis | `{diff}` | `{dependents[]}` |
| `GET` | `/api/v1/repositories/{id}/docs?scope=` | Docs Generation | — | `{markdown}` |
| `POST` | `/api/v1/repositories/{id}/ai/ask` | AI Assistant | `{question}` | `{answer, cited_nodes[]}` |
| `GET` | `/api/v1/health` | — (Phase 1, unchanged) | — | `{state, app_name, version}` |

Every route except `/health` requires `Authorization: Bearer <jwt>` (FR-11.1).

---

## 6. Data flow diagrams

### 6.1 Write path (ingestion)

```
Repository ──► [Import] ──► [Language Detect] ──► [Tree-sitter Parse] ──► [AST Build]
                                                                                │
                                                                                ▼
                                                              [Dependency Graph Generation]
                                                                                │
                                        git history ────────────────────────►  │
                                                                                ▼
                                                                [Knowledge Graph Write]
                                                                                │
                                                                                ▼
                                                                     Neo4j (+ Postgres
                                                                      bookkeeping)
```

### 6.2 Read path (any feature module)

```
Frontend ──HTTP──► api/<module>.py ──► application/<module>/service.py
                                                  │
                                                  ▼
                                   domain/graph/ports.py (narrow sub-port)
                                                  │
                                                  ▼
                                infrastructure/graph/neo4j_reader.py
                                                  │
                                                  ▼
                                              Neo4j ──► results ──► shaped response ──► JSON
```

No arrow in §6.2 ever points at `infrastructure/parsing/` or `infrastructure/git/` (except the
Git Analysis live-diff exception, drawn separately in §7.5) — that absence is the architectural
invariant this whole document exists to enforce.

---

## 7. Sequence diagrams

### 7.1 Full repository import

```
User        API             Ingestion         Postgres        Neo4j
 │  POST /repositories        │                  │              │
 │───────────────────────────►│                  │              │
 │                             │ create ImportJob │              │
 │                             │─────────────────►│              │
 │◄── 202 {import_job_id} ─────│                  │              │
 │                             │ run pipeline (background task)  │
 │                             │ clone, hash-diff │              │
 │                             │─────────────────►│ (FileHash)   │
 │                             │ for each changed file:          │
 │                             │   detect → parse → AST → dep-graph
 │                             │ write subgraph + metrics + history
 │                             │──────────────────────────────────►│
 │                             │ mark job succeeded│              │
 │                             │─────────────────►│              │
 │  GET /import-jobs/{id}      │                  │              │
 │───────────────────────────►│                  │              │
 │◄── {status: succeeded} ─────│                  │              │
```

### 7.2 Search query

```
User → api/search.py → application/search/service.py
                              │ query(text)
                              ▼
                  infrastructure/search/index.py  (SQLite FTS)
                              │ (index built from GraphStructureReader
                              │  reactively after IngestionCompleted —
                              │  not queried here)
                              ▼
                        ranked SearchHit[] → JSON → User
```

### 7.3 Impact analysis (committed code)

```
User → api/impact.py → application/impact/service.py
                              │ get_neighbors(node_id, [CALLS, IMPORTS], depth=N)
                              ▼
                   domain/graph/ports.py::GraphStructureReader
                              ▼
                infrastructure/graph/neo4j_reader.py → Neo4j traversal
                              ▼
                     Subgraph → dependents list → JSON → User
```

### 7.4 AI assistant question (graph-RAG)

```
User → api/ai.py → application/ai/service.py
                        │ 1. retrieve: GraphStructureReader.get_module_graph(scope guess)
                        │    + GraphMetricsReader for relevant nodes
                        ▼
                 build bounded context (node summaries, not raw source)
                        ▼
                 infrastructure/ai/ollama_client.py :: generate(prompt, context)
                        ▼
                 answer + cited node ids → JSON → User
```

### 7.5 Git Analysis — live-diff exception

```
User → api/git.py (live-diff) → application/git_analysis/service.py
                                        │ ONLY this path may call:
                                        ▼
                              infrastructure/git/live_diff.py
                                        │ git diff (working tree vs HEAD)
                                        ▼
                              map changed lines → symbols via the
                              ALREADY-INGESTED graph (GraphStructureReader) —
                              the diff itself is live; symbol resolution is not
                                        ▼
                              changed_symbols[] → JSON → User
```

---

## 8. Class diagrams

Text-UML, interfaces (`<<port>>`) vs. concrete classes vs. value objects (`«value»`), fields
only where they matter to the contract.

### 8.1 AST / dependency graph domain

```
«value» ASTNode (abstract)
  ├─ ASTModule(name, path, imports: list[ASTImport], declarations: list[ASTNode])
  ├─ ASTClass(name, bases: list[str], members: list[ASTNode], span: Span)
  ├─ ASTFunction(name, params: list[ASTParameter], calls: list[ASTCall], span: Span)
  ├─ ASTImport(source: str, symbols: list[str])
  └─ ASTCall(callee: str, span: Span)

«value» Span(start_line, start_col, end_line, end_col)

DependencyGraph
  - nodes: list[GraphNode]
  - edges: list[GraphEdge]
  + merge(other: DependencyGraph) -> DependencyGraph

«value» GraphNode(id: NodeId, type: NodeType, name: str, path: str, span: Span | None)
«value» GraphEdge(source: NodeId, target: NodeId, type: EdgeType)

NodeType  = File | Module | Class | Function | Symbol
EdgeType  = IMPORTS | CALLS | DEFINES | INHERITS | CONTAINS
HistoryEdgeType = CHANGED_IN | AUTHORED_BY
```

### 8.2 Ingestion pipeline

```
<<port>> LanguageDetector
  + detect(path: str, content: bytes) -> Language

<<port>> TreeSitterParser
  + parse(content: bytes, language: Language) -> SyntaxTree

<<port>> ASTBuilder
  + build(tree: SyntaxTree, language: Language) -> ASTModule

<<port>> DependencyGraphBuilder
  + build(ast: ASTModule) -> DependencyGraph

<<port>> KnowledgeGraphWriter        (§5.1)
<<port>> GraphStructureReader        (§5.1)
<<port>> GraphMetricsReader          (§5.1)
<<port>> GraphHistoryReader          (§5.1)

IngestionPipeline
  - repository_import: RepositoryImportService
  - language_detector: LanguageDetector
  - parser: TreeSitterParser
  - ast_builder: ASTBuilder
  - dependency_builder: DependencyGraphBuilder
  - graph_writer: KnowledgeGraphWriter
  + run(repo_id: RepoId) -> ImportJobResult
```

`IngestionPipeline` is the only class in the backend that holds references to every pipeline
stage — no other class is allowed to depend on more than one stage type. This is the concrete
enforcement point for "the repository should never be parsed twice."

### 8.3 Feature module shape (identical pattern across Search/Metrics/Architecture/Impact/Docs/AI)

```
<<router>> api/<module>.py
      │ depends on
      ▼
<module>Service (application/<module>/service.py)
      - reader: <NarrowestSubPort>       ◄── injected, never constructed by the service
      + handle(request: <Module>Request) -> <Module>Response
```

---

## 9. Database schema (PostgreSQL)

Postgres is system-of-record for **bookkeeping**, never for graph structure.

```sql
-- repositories: one row per registered repository
CREATE TABLE repositories (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type   TEXT NOT NULL CHECK (source_type IN ('git_url', 'upload')),
    source_uri    TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    owner_id      UUID REFERENCES users(id)
);

-- import_jobs: one row per import attempt (full or incremental)
CREATE TABLE import_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_id   UUID NOT NULL REFERENCES repositories(id),
    status          TEXT NOT NULL CHECK (status IN
                       ('pending','running','succeeded','failed','partially_failed')),
    stage           TEXT,                       -- current pipeline stage, for progress UI
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    error_summary   TEXT,
    files_processed INTEGER NOT NULL DEFAULT 0,
    files_failed    INTEGER NOT NULL DEFAULT 0
);

-- file_hashes: content hash per file as of the last successful import,
-- the basis of the "never parse twice" incremental diff
CREATE TABLE file_hashes (
    repository_id   UUID NOT NULL REFERENCES repositories(id),
    file_path       TEXT NOT NULL,
    content_hash    TEXT NOT NULL,               -- sha256
    graph_node_id   TEXT NOT NULL,               -- Neo4j node id for this file
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (repository_id, file_path)
);

-- import_job_errors: per-file failures within a job (FR-2.5)
CREATE TABLE import_job_errors (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    import_job_id  UUID NOT NULL REFERENCES import_jobs(id),
    file_path      TEXT NOT NULL,
    stage          TEXT NOT NULL,                -- which pipeline stage failed
    message        TEXT NOT NULL
);

-- users / auth (Phase TBD, stubbed here for FR-11.1)
CREATE TABLE users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Indexes: `file_hashes(repository_id)`, `import_jobs(repository_id, started_at DESC)`,
`import_job_errors(import_job_id)`. Migrations owned by Alembic (already a declared dependency
in `backend/pyproject.toml`).

---

## 10. Neo4j graph schema

**Node labels and properties:**

| Label | Key properties |
|---|---|
| `:Repository` | `id`, `name` |
| `:File` | `id`, `path`, `language`, `content_hash` |
| `:Module` | `id`, `name`, `path` |
| `:Class` | `id`, `name`, `span_start`, `span_end` |
| `:Function` | `id`, `name`, `span_start`, `span_end` |
| `:Symbol` | `id`, `name`, `kind` (variable/constant/type alias) |
| `:Commit` | `sha`, `message`, `authored_at` |
| `:Author` | `email`, `name` |

**Relationship types:**

| Type | From → To | Meaning |
|---|---|---|
| `CONTAINS` | Repository→File, File→Module, Module→Class/Function, Class→Function | Structural containment |
| `IMPORTS` | File/Module → File/Module | Import statement |
| `CALLS` | Function → Function | Call-site edge |
| `INHERITS` | Class → Class | Base-class relationship |
| `DEFINES` | Module/Class → Symbol | Declaration |
| `CHANGED_IN` | File → Commit | Git history |
| `AUTHORED_BY` | Commit → Author | Git history |

**Node properties reserved for precomputed metrics** (written once at ingestion, per FR-3.3):
`loc`, `cyclomatic_complexity`, `fan_in`, `fan_out`, `churn_90d` — attached directly to
`:Function`/`:Class`/`:File` nodes so a read is a property lookup, never a recomputation.

**Constraints/indexes** (declared, not created by hand — via a schema-migration script run at
deploy time, analogous to Alembic for Postgres):
- Uniqueness constraint on `(:File {id})`, `(:Function {id})`, `(:Class {id})`, `(:Symbol {id})`.
- Index on `:File(path)` and `:Commit(sha)` for lookup-by-key queries.

---

## 11. AST schema

Forge's language-agnostic AST is the contract between "language-specific parsing" and
"language-agnostic everything else." Every tree-sitter grammar must map onto this shape.

| Node | Fields |
|---|---|
| `ASTModule` | `name`, `path`, `language`, `imports: list[ASTImport]`, `declarations: list[ASTClass \| ASTFunction \| ASTVariable]` |
| `ASTImport` | `source: str`, `symbols: list[str]`, `alias: str \| None` |
| `ASTClass` | `name`, `bases: list[str]`, `members: list[ASTFunction \| ASTVariable]`, `span: Span` |
| `ASTFunction` | `name`, `params: list[ASTParameter]`, `return_type: str \| None`, `calls: list[ASTCall]`, `span: Span` |
| `ASTParameter` | `name`, `type: str \| None`, `default: str \| None` |
| `ASTCall` | `callee: str`, `span: Span` |
| `ASTVariable` | `name`, `type: str \| None`, `span: Span` |
| `Span` | `start_line`, `start_col`, `end_line`, `end_col` |

Rule: language-specific quirks (e.g., Python decorators, TypeScript generics) are normalized
into this shape at construction time — no downstream stage ever branches on source language.
Information that doesn't fit the model yet is dropped, not stuffed into an untyped `extra`
bag — an AST field only gets added once a real consumer needs it (same "no placeholder code"
discipline Phase 1 already applied to `SystemStatus`).

---

## 12. Dependency graph schema

The in-memory representation produced by Dependency Graph Generation, before it becomes Neo4j
rows. This is intentionally storage-agnostic — the whole reason a future graph-store swap is
possible without touching `domain/dependency/`.

```python
class NodeType(StrEnum):
    FILE = "file"
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    SYMBOL = "symbol"

class EdgeType(StrEnum):
    CONTAINS = "contains"
    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"
    DEFINES = "defines"

@dataclass(frozen=True, slots=True)
class GraphNode:
    id: NodeId
    type: NodeType
    name: str
    path: str
    span: Span | None

@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: NodeId
    target: NodeId
    type: EdgeType

@dataclass(frozen=True, slots=True)
class DependencyGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
```

`NodeId` is a stable, deterministic identifier (e.g. `sha1(repo_id + path + qualified_name)`) —
determinism is what makes the FR-3.1 "upsert is a no-op for unchanged files" guarantee possible.

---

## 13. Knowledge graph schema (logical)

The union of §10 (Neo4j implementation) and the history/metrics layered on top — the model every
consumer module actually programs against via `domain/graph/ports.py`, independent of which
graph engine implements it:

```
Repository
  └─CONTAINS─► File ─CONTAINS─► Module ─CONTAINS─► Class ─CONTAINS─► Function
                 │                                    │                  │
                 │                                  INHERITS          CALLS, DEFINES
                 │                                    ▼                  ▼
                 │                                  Class              Symbol / Function
                 │
               IMPORTS ─► File/Module
                 │
              CHANGED_IN ─► Commit ─AUTHORED_BY─► Author

Every File/Class/Function node additionally carries: loc, cyclomatic_complexity,
fan_in, fan_out, churn_90d  (written once, at ingestion — §10)
```

This is the schema documented for API consumers (frontend, future third-party API users) —
the Neo4j-specific labels/property names in §10 are an implementation detail behind it.

---

## 14. Folder structure

Additive to Phase 1's existing tree — nothing shown here replaces an existing file.

```
backend/src/forge/
  api/
    health.py                 (Phase 1, unchanged)
    repositories.py
    import_jobs.py
    search.py
    architecture.py
    metrics.py
    git.py
    impact.py
    docs.py
    ai.py
  application/
    health_service.py         (Phase 1, unchanged)
    ingestion/
      pipeline.py
      repository_import_service.py
      events.py                (IngestionCompleted + subscriber registration)
    search/service.py
    architecture/service.py
    metrics/service.py
    git_analysis/service.py
    impact/service.py
    docs/service.py
    ai/service.py
    auth/service.py
  domain/
    health.py                  (Phase 1, unchanged)
    repository/entities.py
    parsing/
      language_detector.py
      ast_builder.py
      ast_types.py
    dependency/
      graph_builder.py
      graph_types.py
    graph/
      ports.py                 (KnowledgeGraphWriter/Reader + sub-ports)
    metrics/formulas.py
  infrastructure/
    git/
      client.py                 (clone/pull/hash-diff, ingestion-time)
      live_diff.py               (working-tree diff, Git Analysis exception only)
    parsing/treesitter_client.py
    graph/
      neo4j_writer.py
      neo4j_reader.py
      schema_migration.py
    search/sqlite_fts_index.py
    ai/ollama_client.py
    auth/jwt_provider.py
  core/                         (Phase 1, unchanged)

frontend/src/
  domain/                       (+ types mirroring §13 for each module)
  infrastructure/api/           (+ one typed client per new endpoint group)
  application/                  (+ one hook per module, mirroring health's pattern)
  presentation/
    shell/                      (Phase 1, unchanged)
    search/
    architecture/
    metrics/
    git/
    impact/
    docs/
    chat/
```

---

## 15. File responsibilities

| File | Responsibility |
|---|---|
| `application/ingestion/pipeline.py` | Sequence the six pipeline stages; the only class depending on every stage type (§8.2). |
| `application/ingestion/repository_import_service.py` | Clone/pull, enumerate files, hash-diff, write `ImportJob`/`FileHash`. |
| `application/ingestion/events.py` | Define `IngestionCompleted` and the in-process subscriber registry. |
| `domain/parsing/language_detector.py` | Pure function: path + content → `Language`. |
| `domain/parsing/ast_builder.py` | Pure function: syntax tree → Forge AST (§11). |
| `domain/parsing/ast_types.py` | AST dataclasses (§11) — zero framework imports. |
| `domain/dependency/graph_builder.py` | Pure function: AST → `DependencyGraph` (§12). |
| `domain/dependency/graph_types.py` | `GraphNode`/`GraphEdge`/`DependencyGraph` dataclasses. |
| `domain/graph/ports.py` | `KnowledgeGraphWriter`, `GraphStructureReader`, `GraphMetricsReader`, `GraphHistoryReader` protocols. |
| `domain/metrics/formulas.py` | Pure metric calculations (complexity, fan-in/out) consumed only by the ingestion pipeline. |
| `infrastructure/git/client.py` | Ingestion-time git operations (clone, pull, log for history edges). |
| `infrastructure/git/live_diff.py` | The one live working-tree-diff exception (§7.5). |
| `infrastructure/parsing/treesitter_client.py` | Wraps `tree-sitter` + `tree-sitter-language-pack` grammars. |
| `infrastructure/graph/neo4j_writer.py` | Implements `KnowledgeGraphWriter`. |
| `infrastructure/graph/neo4j_reader.py` | Implements the reader sub-ports. |
| `infrastructure/graph/schema_migration.py` | Applies constraints/indexes from §10 at deploy time. |
| `infrastructure/search/sqlite_fts_index.py` | Implements the search index port; rebuilt on `IngestionCompleted`. |
| `infrastructure/ai/ollama_client.py` | Thin HTTP client to a local Ollama instance; no prompt construction (that's `application/ai/`). |
| `infrastructure/auth/jwt_provider.py` | Issue/verify JWTs. |
| One `service.py` per feature module under `application/<module>/` | FastAPI-independent orchestration for that module's use case(s); depends only on the narrow reader sub-port(s) it needs. |
| One router file per feature module under `api/` | HTTP-only translation to/from that module's service — no business logic (same rule as Phase 1's `api/health.py`). |

---

## 16. Naming conventions

**Python (backend):**
- Files/functions/variables: `snake_case`. Classes: `PascalCase`. Constants: `UPPER_SNAKE_CASE`.
- Port interfaces: suffixed `Reader`, `Writer`, or generically `Port` when neither fits (e.g.
  `AIProviderPort`).
- DTOs crossing a layer boundary: suffixed `Request`/`Response` at the API layer, plain domain
  names (`SystemStatus`, `NodeMetrics`) inside domain/application.
- Value objects: `@dataclass(frozen=True, slots=True)`, matching `domain/health.py`'s existing
  pattern exactly.
- Test files: `test_<module_under_test>.py`, mirroring the source path under `tests/unit/` or
  `tests/integration/`.

**TypeScript (frontend):**
- Components: `PascalCase.tsx`. Hooks: `useCamelCase.ts`. Non-component modules: `camelCase.ts`.
- One component per file; file name matches the exported component name (already the pattern in
  `AppShell.tsx`/`StatusBadge.tsx`).

**Neo4j:**
- Node labels: `PascalCase`, singular (`:File`, not `:Files`).
- Relationship types: `UPPER_SNAKE_CASE`, verbs (`IMPORTS`, `CALLS`).

**PostgreSQL:**
- Tables/columns: `snake_case`, plural table names (`repositories`, `import_jobs`).

**Cross-cutting:**
- `NodeId`/`RepoId`/`FileId` etc. are distinct newtype-style aliases, never raw `str`, so a
  `FileId` can't be passed where a `NodeId` is expected without a type error (mypy strict already
  enforces this project-wide).

---

## 17. Coding standards

- **Ruff + mypy strict** on every backend file, exactly as configured in
  [`backend/pyproject.toml`](../../backend/pyproject.toml) today — no new module gets an
  exemption.
- **Docstring convention**: every module opens with the `Purpose / Responsibility / Depends on /
  Depended on by` header already established in Phase 1's files (see `domain/health.py`,
  `application/health_service.py`) — this is not optional decoration, it's what makes the
  dependency rule in §4 auditable at a glance.
- **Domain layer purity**: `domain/` imports stdlib and other `domain/` modules only — no
  FastAPI, no SQLAlchemy, no `neo4j` driver, no `tree_sitter` imports. This is what makes
  `domain/parsing/`, `domain/dependency/`, and `domain/metrics/` unit-testable without any
  running service.
- **Ports over concrete types**: any application-layer constructor parameter that crosses into
  infrastructure is typed as the port (`GraphStructureReader`), never the concrete
  implementation (`Neo4jReader`) — enforced by code review, later by import-linter.
  Feature modules (`application/search/`, etc.) depend on only the narrowest sub-port(s) they
  actually call.
- **Immutability by default**: domain value objects are frozen dataclasses; mutation happens
  only inside explicitly-named builder functions (`graph_builder.build(...)` returns a new
  `DependencyGraph`, never mutates one in place).
- **No silent catches**: `except Exception:` without re-raising or explicit, logged handling is
  a review-blocking pattern (see §18).
- **Frontend**: functional components + hooks only (no class components), strict `tsconfig`,
  ESLint config as already checked into `frontend/eslint.config.js` — new modules don't relax it.

---

## 18. Error handling strategy

**Exception hierarchy** (`domain/errors.py`, new):

```python
class ForgeError(Exception): ...
class IngestionError(ForgeError): ...
class ParseError(IngestionError): ...          # per-file, caught and recorded, not propagated (FR-2.5)
class UnsupportedLanguageError(IngestionError): ...
class GraphWriteError(ForgeError): ...
class NotFoundError(ForgeError): ...           # unknown repo/node id
class AuthError(ForgeError): ...
```

**Rules:**
- Domain/application code raises `ForgeError` subtypes only — never leaks a raw `neo4jError`,
  `asyncpg` exception, or `httpx` exception past `infrastructure/`. Infrastructure catches
  driver-specific exceptions and re-raises as the matching `ForgeError` subtype.
- The API layer (`api/*.py`) is the single place `ForgeError → HTTP status` translation happens,
  via a FastAPI exception handler registered once in `core/app_factory.py`
  (`NotFoundError → 404`, `AuthError → 401`, `ParseError`/`IngestionError` surfaced as job errors
  not HTTP errors since ingestion is async, everything else → `500` with a correlation id, never
  a stack trace, in the response body).
- **Per-file ingestion failures are data, not exceptions** at the pipeline level — `ParseError`
  for one file is caught inside the pipeline loop, written to `import_job_errors` (§9), and the
  loop continues (FR-2.5). Only a whole-job-level failure (e.g., can't clone the repo at all)
  propagates as a failed `ImportJob`.
- **Transient infrastructure errors** (Neo4j/Postgres connection drop) get a bounded retry with
  backoff at the infrastructure layer; exhausting retries raises `GraphWriteError`, which fails
  the job but leaves prior graph state untouched (FR-1.6 — achieved via upsert semantics, not a
  transaction spanning the whole job).

---

## 19. Logging strategy

Phase 1's `core/logging.py` configures stdlib `logging` with a plain text formatter — sufficient
for a single health endpoint, not sufficient once ingestion jobs and multi-module requests exist.
This phase upgrades it (same file, same responsibility, richer format):

- **Structured JSON logs** in non-development environments (`environment != "development"` still
  gets a human-readable formatter locally; `production`/`test` get JSON) — one log line per
  event, fields: `timestamp`, `level`, `logger`, `message`, `correlation_id`, plus event-specific
  fields.
- **Correlation IDs**: every HTTP request gets a request id (middleware, generated or taken from
  an incoming `X-Request-Id` header); every ingestion job gets a job id (already `ImportJob.id`).
  Every log line emitted while handling that request/job includes it — this is what makes "find
  every log line for this failed import" a single `grep`/query instead of a hunt.
- **What never gets logged**: JWT tokens, password hashes, `.env` values, full file contents.
  File paths and symbol names are fine (they're not secrets).
- **Levels**: `DEBUG` for per-file pipeline stage transitions (verbose, dev-only in practice),
  `INFO` for job start/finish and API request summaries, `WARNING` for per-file parse failures
  (recorded but non-fatal), `ERROR` for job-level failures and unhandled exceptions.

---

## 20. Testing strategy

| Layer | What's tested | How |
|---|---|---|
| `domain/*` | Pure logic: AST building, dependency-graph construction, metric formulas | Fast unit tests, no I/O, no fixtures beyond literal inputs — mirrors Phase 1's health domain test. |
| `application/*` | Orchestration | Unit tests with hand-written fakes of the narrow port(s) each service depends on (cheap because ports are narrow — the ISP payoff from §5.1). |
| `infrastructure/graph/*` | Port implementations | **Contract tests**: one shared test suite (`tests/contracts/graph_reader_contract.py`) run against every `GraphStructureReader` implementation (Neo4j today, an in-memory fake for fast application-layer tests) — guarantees the fake and the real thing agree. |
| `infrastructure/*` (Postgres, Neo4j, Ollama) | Real integration | `tests/integration/`, run against the actual `infra/docker/docker-compose.yml` services in CI — not mocked, since this is where wrong Cypher/SQL actually gets caught. |
| `api/*` | HTTP contract | FastAPI `TestClient`, asserting status codes and response shapes, with application services replaced by fakes (already the pattern proven by Phase 1's health test). |
| End-to-end pipeline | "Does a real small repo ingest correctly" | One golden-repo fixture (a tiny multi-language sample repo checked into `tests/fixtures/`) run through the full pipeline once per CI run, asserting on the resulting graph shape — the one test that would catch "the repo got parsed twice" or a broken stage handoff. |
| Frontend | Component + hook behavior | `vitest` + React Testing Library, same pattern as Phase 1's `StatusBadge.test.tsx`/`useHealthStatus.test.ts` — one test file per new component/hook. |

**Coverage bar**: unchanged from Phase 1's proven baseline — `pytest` and `npm run test` must
stay green, `ruff`/`mypy --strict`/`npm run lint` must stay clean, on every module added under
this spec, no exceptions carved out for "it's just glue code."

---

## 21. Security considerations

- **No code execution.** Ingested repositories are parsed with tree-sitter (a grammar, not an
  interpreter) — Forge never `import`s, `eval`s, or shells out to run code from an ingested
  repository. This holds even for build-config files (`setup.py`, etc.) that a naive tool might
  execute for metadata.
- **Upload handling.** Archive uploads (FR-1.1) are size-capped, extracted into an isolated
  temp directory, and checked for path-traversal (`../` escaping the extraction root) and
  zip-bomb ratios before any file is opened.
- **Credentialed git URLs.** Any credentials in a git URL are used for the clone only, never
  persisted to `repositories.source_uri` in plaintext — stored (if needed for re-pull) via a
  secrets mechanism, not a DB column, and never logged (§19).
- **Secrets management.** `.env` is git-ignored (already true — see `.gitignore`); JWT secret,
  DB credentials, and any future AI provider API keys follow the same rule Phase 1 already
  established for `Settings` — injected via environment, never hardcoded.
- **AuthN/AuthZ.** JWT required on every non-health route (FR-11.1); repository access is scoped
  to `repositories.owner_id` — a user cannot query another user's ingested graph by guessing a
  `repo_id`.
- **Least-privilege datastore credentials.** The backend's Postgres/Neo4j roles have only the
  privileges the pipeline and readers actually need (write access scoped to ingestion, read-only
  roles for anything that only ever reads).
- **Prompt injection.** Repository content (comments, strings, README text) reaches the AI
  assistant as retrieved graph context (§25) — treat it as untrusted input to the LLM prompt,
  same as any other user-influenced content: the system prompt constrains the model to
  answering from the provided context and refusing instructions embedded in that context.
- **Dependency hygiene.** `npm audit` (already 0 vulnerabilities per Phase 1) and an equivalent
  Python check (`pip-audit`, to be added to CI) run on every dependency change, including the
  new backend deps already declared for this phase (`gitpython`, `tree-sitter*`, `python-jose`,
  `passlib`).
- **Rate limiting.** Ingestion is comparatively expensive (§23) — the `POST /repositories` route
  gets per-user rate limiting to prevent resource exhaustion via repeated large imports.

---

## 22. Future scalability

- **Ingestion as a queue-backed worker.** Every pipeline stage already communicates via typed
  DTOs, not shared state (§8.2) — extracting `IngestionPipeline.run()` from an in-process
  background task into a job consumed by Celery/RQ/Arq workers is a change to *how the
  orchestrator is invoked*, not to any stage's logic. This is the intended first extraction when
  a single process's ingestion throughput becomes the bottleneck.
- **Horizontal read scaling.** Feature modules are stateless request handlers reading from
  Neo4j/Postgres/SQLite — running multiple backend replicas behind a load balancer requires no
  code change, only moving the SQLite FTS index (currently implied local-disk) to a shared or
  per-replica-rebuilt store.
- **Search engine swap.** Already a stated Phase 1 requirement (SQLite FTS → Elasticsearch) —
  the port boundary in `infrastructure/search/` is what makes this a new implementation file,
  not a rewrite.
- **Multi-tenant / multi-repo at scale.** `repositories.id` already scopes every graph node
  (via `id` composition, §12) and every Postgres row — sharding by `repository_id` across
  multiple Neo4j databases (Neo4j's multi-database feature) is available without a schema
  redesign if a single instance's graph size becomes a constraint.
- **Caching.** Hot read paths (architecture view for a popular repo, metrics aggregates) can
  gain a Redis-backed cache in front of `GraphStructureReader`/`GraphMetricsReader`
  implementations without changing the port interface or any consumer.
- **Large monorepos.** Incremental ingestion (FR-1.3) is what keeps re-ingestion cheap; for
  genuinely massive monorepos, ingestion can later be parallelized per top-level directory as
  independent sub-jobs feeding the same graph, without changing the single-file pipeline logic.

---

## 23. Performance considerations

- **Incremental ingestion is the primary performance lever** (FR-1.3) — re-ingesting a
  10-file commit should cost roughly 10 files' worth of pipeline time, not the whole repo's.
- **Parse parallelism.** Per-file stages (language detection → parse → AST → dependency graph)
  are independent across files and can run across a process pool; only the final graph-write
  stage needs to serialize (or batch) writes to Neo4j.
- **Batched graph writes.** `KnowledgeGraphWriter.upsert_file_subgraph` is called per file
  logically, but its Neo4j implementation batches into fewer round trips (e.g., `UNWIND`-based
  bulk upserts) rather than one Cypher statement per node/edge.
- **Metrics computed once.** Precomputing metrics at ingestion (FR-3.3) rather than on every
  read is the single biggest read-path performance decision in this spec — it turns "compute
  cyclomatic complexity for 500 functions" into "read 500 already-set properties."
  turns read-time cost from O(source size) to O(result size).
- **Pagination everywhere on graph responses.** Architecture views and impact analysis results
  are depth- and size-bounded by request parameters (FR-5.1, FR-8.1) — no endpoint returns an
  unbounded whole-repo graph in one response.
- **Search index rebuild is asynchronous** (subscribes to `IngestionCompleted`, §5), decoupled
  from the ingestion job's own completion time — a slow index rebuild never blocks an import from
  being marked `succeeded`.

---

## 24. Plugin architecture

Forge stays a modular monolith for v1 (per the review's explicit "avoid unnecessary
microservices" instruction) — "plugin" here means **in-process, statically-registered
extension points**, not dynamically loaded external plugins.

- **New language support** = a new `LanguageDetector` strategy entry + a tree-sitter grammar
  binding registered in `infrastructure/parsing/treesitter_client.py`'s grammar registry.
  No existing pipeline stage changes; `domain/parsing/ast_builder.py` gains a new
  language-specific mapping function alongside (not instead of) the existing ones.
- **New analysis module** (e.g., a future "Security Scanner") = a new `application/<module>/`
  service depending on the existing read ports, a new `api/<module>.py` router registered in
  `core/app_factory.py`, and (if visualized) a new `presentation/<module>/` folder on the
  frontend. Zero changes to the ingestion pipeline or to any other feature module — this is the
  concrete payoff of the read-port boundary (§4).
- **New AI provider** = a new `infrastructure/ai/<provider>_client.py` implementing the same
  `AIProviderPort` (§25) as `ollama_client.py` — `application/ai/service.py` doesn't know which
  one is wired in.
- **Registration is explicit, not magic.** Every new router, grammar, or provider is registered
  by an explicit line in a factory/registry function (matching Phase 1's `app_factory.py`
  pattern of `app.include_router(...)`) — no filesystem auto-discovery, so `git blame` on the
  registry always shows exactly when and why something was added.

---

## 25. AI integration strategy

- **Local-first, v1.** `infrastructure/ai/ollama_client.py` talks to a local Ollama instance —
  no repository content leaves the deployment by default, matching the privacy stance implied by
  Phase 1's tech-stack choice (`AI: Ollama (local models)`).
- **Graph-RAG, not raw-file-RAG.** Context for both the AI assistant (FR-10.1) and
  documentation generation (FR-9.1) is retrieved via `GraphStructureReader`/
  `GraphMetricsReader` — node summaries (name, signature, docstring, key metrics, immediate
  neighbors) — never the raw file tree. This is a direct consequence of the "never parse twice"
  rule: the AI module has no license to open source files either.
- **Bounded context construction.** `application/ai/service.py` owns turning a retrieved
  subgraph into a token-bounded prompt (truncation/prioritization strategy: closest neighbors
  and highest-fan-in nodes first) — `infrastructure/ai/ollama_client.py` only sends/receives,
  it never shapes context.
- **Provider abstraction.**
  ```python
  class AIProviderPort(Protocol):
      def generate(self, prompt: str, context: list[GraphNodeSummary]) -> str: ...
  ```
  `ollama_client.py` implements this today; a future cloud-LLM client can implement it later
  behind the same interface without touching `application/ai/` or `application/docs/`.
- **Grounding discipline.** The system prompt requires citing which graph nodes an answer draws
  from (FR-10.1's `cited_nodes[]`) and requires an explicit "I don't have enough information in
  the graph to answer that" response rather than falling back to the model's general knowledge —
  this is a product-trust requirement, not just a nicety, given the tool's whole premise is
  "answers grounded in your actual codebase."
- **No fine-tuning in v1.** Prompt + retrieved context is the entire strategy; fine-tuning is
  explicitly out of scope until there's usage data to justify it.

---

## 26. Risks and tradeoffs

| Risk | Impact | Mitigation / accepted tradeoff |
|---|---|---|
| Neo4j operational complexity | Higher ops burden than a pure-SQL stack once deployed beyond `docker-compose` | Accepted for v1 (graph queries are the product's core value); revisit only if a managed Neo4j offering or an embedded graph engine changes the calculus. |
| Tree-sitter grammar coverage/version drift | A language upgrade could silently change parse output, corrupting graph structure for that language | Pin grammar versions per language in `pyproject.toml`; golden-repo end-to-end test (§20) catches structural drift on grammar bumps. |
| Incremental ingestion correctness | Content-hash diffing (FR-1.3) doesn't detect a file *rename* as a rename — it looks like a delete + add, potentially losing history continuity for that node | Accepted for v1; rename detection (via git's own rename heuristics, already available through `gitpython`) is a documented future enhancement to Repository Import, not a v1 blocker. |
| Single ingestion pipeline as a throughput bottleneck | Large monorepos ingest slowly on one process | Mitigated by per-file parallelism (§23) now; queue-based worker extraction (§22) is the designed escape hatch, deliberately not built until needed (avoids overengineering). |
| Local LLM (Ollama) quality/latency vs. a cloud model | Weaker answers or slower responses than GPT/Claude-class hosted models | Accepted tradeoff for v1 privacy stance; the `AIProviderPort` abstraction (§25) means switching to a hosted model later is additive, not a rewrite, if product needs outweigh the privacy tradeoff. |
| SQLite FTS scalability ceiling | Search degrades on very large repos/many repos | Already an explicitly designed swap point (SQLite FTS → Elasticsearch) — not a redesign risk, a scheduled migration. |
| Architecture erosion without enforcement | The layer/port rules in this document are conventions until import-linter actually runs in CI (§17) — a rushed PR could add a direct `infrastructure/graph` import into `application/search/` and nothing would catch it today | Treat "wire import-linter into CI enforcing §4/§5's dependency rules" as a near-term task, not a someday item — it's the difference between this document being binding and being aspirational. |
| Partial-ingestion semantics complexity | FR-1.6/FR-2.5's "partial failures don't corrupt prior state" requires real care in how upserts are transacted — getting this wrong silently corrupts the graph | Contract tests (§20) against the `KnowledgeGraphWriter` port must include a partial-failure scenario, not just the happy path, before this ships. |

---

*This specification will be extended, not replaced, as each module above moves from blueprint to
implementation — analogous to how `01-system-architecture.md` was extended by this document
rather than rewritten.*
