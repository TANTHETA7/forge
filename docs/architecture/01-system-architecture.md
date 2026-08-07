# Forge — Phase 1: System Architecture

> Status: **Complete**. This is the foundation every later phase (Repository Import, Parser
> Engine, AST Engine, Dependency Engine, Knowledge Graph, …) builds on top of. Nothing here
> should need to change shape later — only grow.

## 1. Why a monorepo, two deployables

Forge ships two independently deployable artifacts that share nothing at the source level:

- **`backend/`** — a Python 3.12 / FastAPI service. Owns all analysis: parsing, graph
  construction, metrics, git history, AI context building.
- **`frontend/`** — a React/TypeScript/Vite SPA. Owns visualization and interaction only. It
  never talks to Postgres or Neo4j directly — only to the backend's HTTP API.

They live in one repository (`forge/`) so that architecture docs, Docker Compose, and CI stay
co-located and versioned together, but each has its own dependency manifest and can be built,
tested, and deployed on its own. This is the standard shape for developer-tool products (see
Sourcegraph, GitHub's own monorepo split) — a single graph/analysis backend serving one or more
thin clients.

## 2. Layered architecture (applies inside `backend/` and, adapted, inside `frontend/`)

```
┌─────────────────────────────────────────────────────────────┐
│  Presentation Layer                                          │
│  Backend:  --                (no HTML rendering; API is the  │
│                                presentation boundary)         │
│  Frontend: presentation/     (React components, pages, views) │
├─────────────────────────────────────────────────────────────┤
│  API Layer                                                    │
│  Backend:  api/               (FastAPI routers, request/response│
│                                 schemas, HTTP status mapping)  │
│  Frontend: infrastructure/api (typed HTTP client consuming     │
│                                 backend's API layer)           │
├─────────────────────────────────────────────────────────────┤
│  Application Layer                                             │
│  Backend:  application/       (use cases / services — orchestrate│
│                                 domain objects, no HTTP, no SQL)│
│  Frontend: application/       (hooks, view-state, orchestration)│
├─────────────────────────────────────────────────────────────┤
│  Domain Layer                                                  │
│  Backend:  domain/             (entities, value objects, ports │
│                                  — pure Python, zero framework  │
│                                  imports)                       │
│  Frontend: domain/              (TS types/interfaces mirroring │
│                                   backend domain contracts)     │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Layer                                          │
│  Backend:  infrastructure/     (Postgres via SQLAlchemy, Neo4j │
│                                  driver, filesystem, git, LLM   │
│                                  clients — implements domain    │
│                                  ports)                         │
│  Frontend: infrastructure/     (fetch/HTTP, browser storage)   │
└─────────────────────────────────────────────────────────────┘
```

**Dependency rule (strict, enforced by code review + import-linter in CI later):**
`api → application → domain ← infrastructure`. Domain depends on nothing. Infrastructure
implements interfaces (ports) that domain/application define — this is the Dependency
Inversion Principle applied at the package level, and it's what lets us swap Postgres for
another store, or SQLite FTS for Elasticsearch, without touching business logic (see the
mandated "Search: SQLite FTS → Elasticsearch" swap — this is *why* that requirement is easy).

`core/` is a cross-cutting slice (config, logging, DI wiring) that every layer may import —
it contains no business logic, only plumbing.

## 3. Why this specific folder layout and not something flatter

Three alternatives were considered:

| Option | Verdict |
|---|---|
| **Flat `app/` with `models.py`, `routes.py`, `services.py`** | Rejected — works for a CRUD app, collapses once Forge has 12+ modules (Parser, AST, Dependency Engine, Knowledge Graph, Metrics, Impact, Git, Docs, AI…). Every file becomes a god file. |
| **One folder per feature module (`parser/`, `dependency_engine/`, …) each with its own api/application/domain/infrastructure** | Strong option, and this is exactly what Forge will look like by Phase 5+. Premature in Phase 1 — there are no modules yet, so feature-first folders would be empty scaffolding (violates "never create unnecessary files"). |
| **Layer-first at the top, feature-first inside each layer once modules exist** | **Chosen.** Phase 1 establishes the four layers with only `core/` populated (config/logging — the one thing every future module needs). Starting in Phase 2 (Repository Import), each new module gets its own subpackage *inside* `api/`, `application/`, `domain/`, `infrastructure/` (e.g. `domain/repository/`, `application/repository/`). By the time 5–6 modules exist, the tree naturally reads as feature-sliced within each layer — no restructuring required, no empty folders today. |

This mirrors how Sourcegraph and SonarQube's server codebases evolved: layers first, then
feature slices inside layers, never the reverse (feature-first-from-day-one leaves you with
either 12 empty module folders now, or a big-bang restructure later — both are worse).

## 4. Request lifecycle (sequence)

Every feature module will follow this exact path. Phase 1 implements it end-to-end for a
single trivial slice — `GET /health` — specifically so the shape is proven before any real
logic is built on top of it.

```
Browser / Frontend
      │  GET /health
      ▼
FastAPI app (core/app_factory.py)
      │  routed by
      ▼
api/health.py            (Presentation/API layer — HTTP concern only)
      │  calls
      ▼
application/health_service.py   (Application layer — orchestration, no HTTP types)
      │  reads
      ▼
domain/health.py          (Domain layer — pure value object: SystemStatus)
      │  (no infrastructure needed for health; future endpoints add this hop)
      ▼
infrastructure/*          (e.g. Postgres ping, Neo4j ping — added when those
                            backing services exist, Phase 2+)
      │
      ▼
JSON response ──► Frontend infrastructure/api/client.ts ──► React Query cache
      │
      ▼
presentation/shell/StatusBadge.tsx renders it
```

## 5. Configuration & settings (`core/config.py`)

A single `Settings` class (pydantic-settings) is the **one** source of runtime configuration,
loaded once from environment variables / `.env`. Every other module receives configuration by
dependency injection (FastAPI's `Depends(get_settings)`), never by importing `os.environ`
directly. This keeps every service testable — tests inject a `Settings` built from literals,
no environment mutation required.

## 6. What Phase 1 deliberately does NOT include

To honor "avoid overengineering" and "never write placeholder code":

- **No Postgres/Neo4j models yet.** They have no schema until Phase 2 (Repository Import)
  and Phase 5 (Dependency Engine / Knowledge Graph) define what needs persisting. An empty
  `models.py` today would be a placeholder.
- **No auth yet.** JWT auth is a real module (Phase TBD) with its own domain concepts (User,
  Token). Stubbing "fake auth" now would be thrown away, not built on.
- **No React Flow / Cytoscape / Monaco wiring yet.** The frontend `package.json` declares
  these dependencies now (Dependency Management is an explicit Phase 1 deliverable) so the
  lockfile and toolchain are proven working, but no visualization component is written until
  there is a graph to visualize (Phase 5+).
- **No Docker images for the app itself.** `infra/docker/docker-compose.yml` stands up the two
  *backing services* (Postgres, Neo4j) that later phases need to develop against. Backend/
  frontend containers arrive when there's an actual deployment target to test against.

## 7. Module → future layer mapping (reference for later phases)

| Module (from project spec) | Backend home | Frontend home |
|---|---|---|
| Repository Import Service | `domain/repository/`, `application/repository/`, `infrastructure/git/` | `presentation/repository/` |
| Parser Engine / AST Engine | `domain/parsing/`, `infrastructure/parsing/` (tree-sitter) | — (server-side only) |
| Dependency Engine | `domain/dependency/`, `application/dependency/` | `presentation/graph/` |
| Knowledge Graph | `infrastructure/graph/` (Neo4j) | `presentation/graph/` |
| Search Engine | `infrastructure/search/` (SQLite FTS → swappable) | `presentation/search/` |
| Metrics Engine | `domain/metrics/`, `application/metrics/` | `presentation/metrics/` |
| Impact Analyzer | `application/impact/` | `presentation/impact/` |
| Git Analyzer | `infrastructure/git/` | `presentation/git/` |
| Documentation Generator | `application/docs/` | `presentation/docs/` |
| AI Assistant | `application/ai/`, `infrastructure/ai/` (Ollama client) | `presentation/chat/` |

This table is the contract that keeps every future phase from guessing where new code belongs.
