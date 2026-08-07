# Forge Backend

FastAPI service implementing Forge's analysis engine. See
[`../docs/architecture/01-system-architecture.md`](../docs/architecture/01-system-architecture.md)
for the layered architecture this package follows.

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
copy .env.example .env
```

## Run

```bash
uvicorn forge.main:app --reload --app-dir src
```

Then visit `http://localhost:8000/api/v1/health` and `http://localhost:8000/docs`.

## Test

```bash
pytest
```

## Layout

```
src/forge/
  api/             Presentation/API layer — FastAPI routers + wire schemas
  application/     Application layer — use cases, no HTTP/SQL imports
  domain/          Domain layer — entities & value objects, zero framework imports
  infrastructure/  Infrastructure layer — Postgres/Neo4j/git/LLM clients (empty until Phase 2)
  core/            Cross-cutting: settings, logging, app assembly
tests/
  unit/            Application + domain layer tests, no I/O
  integration/     Full-stack tests through the ASGI app
```
