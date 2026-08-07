# Forge

**Turn Code Into Knowledge.**

Forge is an AI-powered software intelligence platform: upload a repository and it builds a
queryable knowledge graph of its architecture, dependencies, metrics, and history.

## Status

**Phase 1 — System Architecture, Folder Structure, Project Setup, Dependency Management: done.**

A vertical slice (`GET /health`) is wired end to end through every layer on both sides —
backend and frontend — to prove the architecture before any real feature is built on top of
it. See [`docs/architecture/01-system-architecture.md`](docs/architecture/01-system-architecture.md)
for the full design rationale.

No other module (Repository Import, Parser Engine, Dependency Engine, ...) has been started yet.

## Repository layout

```
forge/
  docs/architecture/   Design docs — read 01-system-architecture.md first
  backend/              FastAPI service (Python 3.12) — see backend/README.md
  frontend/             React + TypeScript SPA (Vite) — see frontend/README.md
  infra/docker/         docker-compose.yml for Postgres + Neo4j — see infra/docker/README.md
```

## Quick start

```bash
# 1. Backing services
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

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | React, TypeScript, TailwindCSS, Vite, React Flow (`@xyflow/react`), Cytoscape.js, Monaco Editor |
| Backend | FastAPI, Python 3.12 |
| Relational store | PostgreSQL |
| Graph store | Neo4j |
| Parsing | Tree-sitter |
| Auth | JWT |
| Search | SQLite FTS (swappable for Elasticsearch behind the same port) |
| AI | Ollama (local models) |

## Verified working (Phase 1)

- Backend: `pytest` (5/5 passing), `ruff check` (clean), `mypy --strict` (clean), live
  `uvicorn` smoke test against `/api/v1/health`.
- Frontend: `npm run build` (clean), `npm run lint` (clean), `npm run test` (4/4 passing),
  `npm audit` (0 vulnerabilities).
- `infra/docker/docker-compose.yml` validated for YAML correctness; **not** run end-to-end —
  Docker wasn't available in the scaffolding environment. Run it yourself before Phase 2.

## Contributing to your own build

This repo is not yet a git repository (by request, while Phase 1 was being scaffolded).
Initialize it and make the first commit whenever you're ready:

```bash
git init
git add .
git commit -m "Phase 1: system architecture, folder structure, project setup, dependency management"
```
