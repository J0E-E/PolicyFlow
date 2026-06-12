# core

The `core` FastAPI service. It runs under uvicorn in the compose stack on the
internal `policyflow-internal` network (no host port — nginx is the sole entry
point, added in Epic 4). It exposes `GET /api/health`, which probes PostgreSQL
(asyncpg `SELECT 1`) and RabbitMQ (aio-pika connect/close) and reports each
result. All checks ok returns `200` with `{"status":"ok","version":<sha>,
"checks":{"db":"ok","broker":"ok"}}`; any failing check returns `503` with
`status:"degraded"` and that check marked `"error"`, which drives the container
health check `unhealthy`.

Hit it from inside the network:

```
docker compose exec core curl -s localhost:8000/api/health
```

## Migrations on boot

Alembic migrations run automatically as a boot step, never manually. The
container entrypoint (`entrypoint.sh`) runs **migrate → seed → serve** in order:

1. `alembic upgrade head` applies migrations.
2. `python -m app.seed` runs the seed (`app/seed.py`), which idempotently
   seeds the demo personas — two demo tenants and nine demo users (the full
   RBAC role matrix) — inserting only what is absent on each boot.
3. uvicorn starts and serves the app.

The entrypoint uses `set -e`, so if migrate (or seed) fails the container exits
non-zero and **fails its boot** rather than serving a half-migrated app.

The baseline migration (`alembic/versions/0001_empty_baseline.py`) is empty —
its `upgrade()`/`downgrade()` are no-ops, so running it creates only Alembic's
`alembic_version` bookkeeping table. Real schema arrives in P1+. Migrations run
synchronously via psycopg (`env.py` rewrites the `DATABASE_URL` scheme to
`postgresql+psycopg://`); the async asyncpg health probe is untouched.
