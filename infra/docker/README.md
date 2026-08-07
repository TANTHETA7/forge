# Infra: backing services

```bash
cd infra/docker
docker compose up -d
```

Starts:

- **Postgres 16** on `localhost:5432` (`forge` / `forge`, database `forge`) — matches
  `backend/.env.example`'s `POSTGRES_DSN` default.
- **Neo4j 5** on `localhost:7687` (Bolt) and `localhost:7474` (browser UI), user `neo4j`,
  password `forge-dev-password` — matches `backend/.env.example`'s `NEO4J_*` defaults.

Stop with `docker compose down`; add `-v` to also drop the named volumes and start clean.

> **Not verified in this environment** — Docker isn't installed on the machine this was
> scaffolded on, so this compose file has been checked for YAML validity and reviewed against
> the Postgres/Neo4j official image docs, but not run end-to-end. Run `docker compose up -d`
> and confirm both containers report healthy (`docker compose ps`) before starting Phase 2,
> which is the first phase that actually connects to Postgres.
