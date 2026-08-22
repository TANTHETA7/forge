# Forge

**Turn Code Into Knowledge.**

Forge is an AI-powered software intelligence platform: import a repository and it builds a
queryable knowledge graph of its architecture, dependencies, metrics, and history.

## Status

**Phases 1–6 are implemented on the backend.** The analysis pipeline runs end to end: import a
repository, parse it into a normalized code model, resolve dependencies between the pieces,
project the result into Neo4j, and query that graph for impact, paths, statistics, and insights.

| Phase | Scope | Design doc |
|---|---|---|
| 1 | **System architecture** — hexagonal layering (`domain` / `application` / `infrastructure` / `api`), config, logging, error handling, and a `GET /health` vertical slice through every layer on both sides | [01-system-architecture.md](docs/architecture/01-system-architecture.md) |
| 2 | **Repository import** — ZIP upload and Git clone sources into an isolated per-repository workspace, metadata scan, `PENDING → IMPORTING → READY \| FAILED` lifecycle | [02-engineering-specification.md](docs/architecture/02-engineering-specification.md) (blueprint) |
| 3 | **Parser engine** — tree-sitter parsers for Python / JavaScript / TypeScript, producing a normalized `ParsedFile` / `Symbol` / `Parameter` / `Import` model in PostgreSQL | [03-parser-engine.md](docs/architecture/03-parser-engine.md) |
| 4 | **Dependency analysis** — resolves Phase 3's model into explicit `DependencyEdge` rows: file→file `IMPORTS`, function→function `CALLS`, class→class `INHERITS`, each marked `RESOLVED` / `AMBIGUOUS` / `UNRESOLVED`; deterministic IDs make re-analysis idempotent | [04-dependency-analysis.md](docs/architecture/04-dependency-analysis.md) |
| 5 | **Knowledge graph** — projects the already-resolved PostgreSQL data into Neo4j (repository / file / symbol nodes; `CONTAINS`, `DEFINES`, `IMPORTS`, `CALLS`, `INHERITS` relationships). Performs no analysis of its own and never projects `AMBIGUOUS` / `UNRESOLVED` edges | [05-knowledge-graph.md](docs/architecture/05-knowledge-graph.md) |
| 6 | **Code intelligence** — turns the projection into a query layer: multi-hop impact analysis, shortest dependency paths, degree statistics, and insights (most-connected files, dependency hotspots, isolated nodes, mutual-import pairs) | [06-code-intelligence.md](docs/architecture/06-code-intelligence.md) |

Each phase doc describes the implementation **as it actually exists**, with deliberate gaps
called out under "Known limitations" rather than implied away. Two worth knowing up front:
symbol resolution handles `self.` / `this.` one level deep only (Phase 4 §9), and the
circular-dependency signal is a direct 1-hop `A ↔ B` mutual-import check, **not** general cycle
detection (Phase 6 §9).

**The frontend is still Phase 1 only** — the app shell plus the health-status slice. None of the
Phases 2–6 API surface is wired into the UI yet; it is exercised through `/docs` and the tests.

## Repository layout

```
forge/
  docs/architecture/    Design docs — read 01-system-architecture.md first
  backend/              FastAPI service (Python 3.12) — see backend/README.md
    src/forge/
      domain/           Entities and ports, one package per bounded context
      application/      Use-case services orchestrating the ports
      infrastructure/   Adapters: parsing, persistence, graph, sources, workspace
      api/              FastAPI routers and schemas
      core/             Config, logging, app factory
    tests/unit/         20 unit suites (no external services needed)
    tests/integration/  17 API + live Postgres/Neo4j suites
  frontend/             React + TypeScript SPA (Vite) — see frontend/README.md
  infra/docker/         docker-compose.yml for Postgres + Neo4j — see infra/docker/README.md
```

## API surface

All routes are mounted under `API_V1_PREFIX` (default `/api/v1`). Analysis routes are scoped per
repository: `/projects/{project_id}/repositories/{repository_id}`.

| Phase | Endpoints |
|---|---|
| 1 | `GET /health` |
| 2 | `POST /projects`, `GET /projects/{id}`, `POST …/repositories/import/zip`, `POST …/repositories/import/git`, `GET …/repositories/{id}` |
| 3 | `POST …/parse`, `GET …/files`, `GET …/symbols`, `GET …/symbols/{id}`, `GET …/parse-errors` |
| 4 | `POST …/analyze-dependencies`, `GET …/dependencies`, `GET …/dependencies/{id}` |
| 5 | `POST …/graph/project`, `GET …/graph/nodes`, `GET …/graph/dependencies`, `GET …/graph/neighbors/{node_id}` |
| 6 | `GET …/graph/nodes/{id}/dependencies`, `GET …/graph/nodes/{id}/dependents`, `GET …/graph/nodes/{id}/impact`, `GET …/graph/path`, `GET …/graph/statistics`, `GET …/graph/insights` |

Typical pipeline for one repository: `import/zip` → `parse` → `analyze-dependencies` →
`graph/project` → query Phase 6.

## Quick start

```bash
# 1. Backing services (required for everything except /health)
cd infra/docker && docker compose up -d && cd ../..

# 2. Backend
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
uvicorn forge.main:app --reload --app-dir src
# -> http://localhost:8000/docs

# 3. Frontend (new terminal)
cd frontend
npm install
copy .env.example .env.local
npm run dev
# -> http://localhost:5173
```

The backend does **not** connect to PostgreSQL or Neo4j at startup — engines are created lazily,
so it boots without Docker and `GET /health` answers. Every DB-backed route fails at request
time until the backing services are up.

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | React, TypeScript, TailwindCSS, Vite, React Flow (`@xyflow/react`), Cytoscape.js, Monaco Editor |
| Backend | FastAPI, Python 3.12 |
| Relational store | PostgreSQL (SQLAlchemy 2 async + asyncpg, Alembic) |
| Graph store | Neo4j (official `neo4j` driver, Bolt) |
| Parsing | Tree-sitter (`tree-sitter-language-pack`) — Python, JavaScript, TypeScript |
| Repository sources | ZIP upload, Git clone (GitPython) |
| Auth | JWT (dependencies installed; **not yet implemented**) |
| Search | SQLite FTS, swappable for Elasticsearch behind the same port (**not yet implemented**) |
| AI | Ollama, local models (**not yet implemented**) |

The frontend's graph and editor libraries (React Flow, Cytoscape, Monaco) are installed and
build clean but are not used by any component yet — they were chosen in Phase 1 and are waiting
on the visualization phase.

## Verified working

Last run on the current tree (`d698074`):

**Backend**
- `pytest` — **296 passed, 91 skipped** in ~5 min. The skips are the integration suites that
  require live PostgreSQL and Neo4j; they skip cleanly when the services are absent.
- `ruff check .` — clean.
- `mypy --strict src` — clean, 93 source files.

**Frontend**
- `npm run build` — clean (`tsc -b && vite build`).
- `npm run lint` — clean.
- `npm run test` — **4 passed**, 2 files.

**Not verified:** `infra/docker/docker-compose.yml` has been validated for YAML correctness but
not run end to end here — Docker was unavailable. Bring it up yourself before relying on the
91 skipped integration suites or any DB-backed route.
