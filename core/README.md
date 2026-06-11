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

Alembic database migrations land here in Epic 3.
