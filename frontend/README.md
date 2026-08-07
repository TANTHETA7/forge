# Forge Frontend

React + TypeScript + Vite SPA. See
[`../docs/architecture/01-system-architecture.md`](../docs/architecture/01-system-architecture.md)
for the layered architecture this package follows.

## Setup

```bash
cd frontend
npm install
copy .env.example .env.local
```

## Run

```bash
npm run dev
```

Visit `http://localhost:5173` (requires the backend running on `:8000` for the status badge
to resolve — see `../backend/README.md`).

## Test / Lint / Build

```bash
npm run test
npm run lint
npm run build
```

## Layout

```
src/
  presentation/     UI components and pages — no fetching, no business logic
  application/       Hooks orchestrating use cases — React state, no DOM/fetch details
  domain/             TypeScript types mirroring backend domain contracts
  infrastructure/     fetch-based API clients — the only layer that talks HTTP
```

## Dependencies declared ahead of use

`@xyflow/react`, `cytoscape`, and `monaco-editor` are declared in `package.json` now
(Phase 1's "Dependency Management" deliverable covers the full mandated tech stack) but are
not yet imported anywhere — they're wired up starting with the Dependency Engine /
Knowledge Graph visualization phases.
