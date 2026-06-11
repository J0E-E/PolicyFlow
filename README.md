# PolicyFlow

PolicyFlow is a multi-tenant policy platform. The repository is a monorepo holding
the React SPA (`frontend/`), the FastAPI core service (`core/`), the Terraform
infrastructure (`infra/`), and the deploy hook scripts (`ops/`). The same
`docker-compose.yml` runs locally and in production for local/prod parity.

## Run locally

```sh
cp .env.example .env
docker compose up
```

This brings up the health-checked PostgreSQL and RabbitMQ backing services.
Application containers (core, frontend, nginx) land in later epics.
