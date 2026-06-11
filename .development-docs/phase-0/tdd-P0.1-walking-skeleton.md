# Walking Skeleton & Deployment Pipeline (P0.1) — Technical Design Document

> Phase **P0.1** of the [PolicyFlow Program & Phase Plan](../program-and-phase-plan.md).
> Behavioral spec: [PolicyFlow_Requirements.md](../PolicyFlow_Requirements.md) →
> "Phase 0: Walking Skeleton & Deployment Pipeline", "Deployment & Infrastructure",
> "Application Stack".

## 1. Summary

Stand up the complete runtime **topology** and the complete **delivery path** for
PolicyFlow before any feature exists. We build a single Docker stack — nginx ▸ React
SPA shell ▸ FastAPI core placeholder ▸ RabbitMQ + PostgreSQL — that runs identically
on a developer's machine (one command) and on a single always-on AWS EC2 instance.
All AWS resources are provisioned by Terraform; pushes to `main` flow through AWS
CodePipeline (CodeBuild → ECR → CodeDeploy) and land on the EC2 host with **zero
manual steps**. The slice is "done" when a trivial change pushed to GitHub appears at
`https://policyflow.joeyshub.com` automatically. No domain features, auth, schema, or
event consumers are built here — only the skeleton they will all later land on.

## 2. Business Requirements

Lifted from the requirements doc (Phase 0 + Deployment & Infrastructure + Application
Stack):

- Repository + Docker stack definition (nginx, frontend, core-app placeholder, broker,
  database) running locally via a **single command**, fully seeded.
- The **same stack definition** runs locally and in the cloud (local/prod parity).
- Terraform provisions **all** AWS resources (EC2, networking/security groups, IAM,
  Route 53 records, pipeline resources, artifact storage). No console-managed
  resources except two sanctioned exceptions: the pre-existing Route 53 hosted zone
  (referenced, never created) and one-time interactive bootstrap (e.g. authorizing the
  CodePipeline GitHub connection).
- CodePipeline + CodeDeploy wired to GitHub pushes, deploying to production.
- Minimal landing page + minimal tenant-selection screen (placeholder versions) served
  over **HTTPS** on `policyflow.joeyshub.com`.
- nginx is the **sole public entry point**, reverse-proxying both the SPA and the API.
- Secrets (master encryption key, DB + broker credentials) live in **AWS SSM Parameter
  Store** as SecureStrings; values injected out-of-band, never in repo/code/state.
- Scheduled jobs run **inside the stack** (no host cron) — pattern established now.
- Schema migrations + seed run as **deploy steps**, never manually. DB reset on deploy
  is acceptable; nothing must survive a deploy before go-live.
- **Exit test:** a change pushed to GitHub appears at the production URL with no manual
  steps.

## 3. Goals / Non-Goals

**Goals**
- Prove hands-off push→build→deploy→live on a parity stack.
- Stand up the full container topology (nginx, frontend, core, RabbitMQ, Postgres).
- Provision 100% of AWS infra via Terraform.
- Serve placeholder landing + tenant-selection over HTTPS on the committed domain.
- Establish the permanent seams: Alembic + deploy-time migrate/seed hook; SSM secrets;
  in-stack scheduling pattern.

**Non-Goals** (owned elsewhere — do not build here)
- Auth/RBAC (→ P1.1), tenant scoping / schema-per-tenant (→ P1.2), encryption/blind index (→ P1.3),
  audit (→ P1.4).
- Domain schema/entities and real seed data (→ P1+ / P1.8).
- Event **consumers**/sidecars (→ P1.5 stubs, M3 real). *Note:* RabbitMQ is provisioned
  and reachable in P0.1, but no producers/consumers are wired.
- Real landing/tenant-selection content (→ P1.6).
- Any dashboard, demo session, or workflow logic.

## 4. Current State

Greenfield. The repository currently contains only design docs under
[.development-docs/](../) (this TDD, the [program plan](../program-and-phase-plan.md),
the [requirements](../PolicyFlow_Requirements.md), the
[UI/UX Guide](../UI_UX_Guide.md)) and `.claude/` pipeline tooling. There is no
application code, no `docker-compose`, no Terraform, no CI/CD. Constraints that bind
this design:

- [CLAUDE.md](../../.claude/CLAUDE.md): an `id` on every HTML element; descriptive
  naming; small focused React components; consult the UI/UX Guide before any UI.
- Application stack is **committed**: React SPA (nginx-served) + Python/FastAPI; one
  repo; real message broker between processes.
- Deployment is **committed**: single Docker stack, one small always-on EC2, Terraform
  for all AWS, SSM for secrets, HTTPS on `policyflow.joeyshub.com` via Route 53, CI/CD
  via CodePipeline + CodeDeploy.
- `joeyshub.com` is a registered domain the author owns, with a Route 53 hosted zone
  available (referenced by Terraform, never created).

## 5. Proposed Design

### 5.1 High-level approach

One `docker-compose.yml` defines every runtime component. The identical file runs
locally and on EC2 (parity); local-only conveniences (bind mounts, hot reload) live in
a `docker-compose.override.yml` that is not used in prod. nginx is the single public
entry: it serves the built React SPA as static files and reverse-proxies `/api/*` to
the FastAPI core. RabbitMQ and PostgreSQL are internal-only services on the compose
network (no public ports). Terraform provisions the AWS substrate; CodePipeline builds
images in CodeBuild, pushes them to ECR, and CodeDeploy pulls + restarts the stack on
the EC2 host.

### 5.2 Container topology

```text
                       Internet (443)
                            │
                    ┌───────▼────────┐   policyflow.joeyshub.com
                    │     nginx      │   TLS terminates here (certbot)
                    │ (sole entry)   │
                    └───┬────────┬───┘
              static SPA│        │ /api/* reverse proxy
                  ┌─────▼──┐  ┌──▼─────────┐
                  │frontend│  │ core (API) │  FastAPI, /api/health
                  │(build) │  │  FastAPI   │
                  └────────┘  └──┬──────┬──┘
                                 │      │  (internal network only)
                          ┌──────▼─┐  ┌─▼────────┐
                          │postgres│  │ rabbitmq │  (mgmt UI internal)
                          └────────┘  └──────────┘
```

Components:
- **nginx** — public on 443 (and 80 → redirect + ACME HTTP-01 challenge). Serves SPA
  static build; proxies `/api/` to core. Holds the Let's Encrypt cert.
- **frontend** — build stage produces static assets; in prod they are served by nginx
  (copied into the nginx image or a shared volume). Locally, may run the Vite dev
  server behind the override file.
- **core** — FastAPI app exposing `GET /api/health` (returns `{status, version, time}`
  after checking DB + broker reachability). Runs Alembic on a deploy/boot hook.
- **postgres** — PostgreSQL, internal only, named volume for data.
- **rabbitmq** — RabbitMQ with management plugin, internal only. Provisioned and
  reachable; no queues/consumers wired in P0.1.

### 5.3 AWS infrastructure (Terraform)

```text
Route 53 (existing zone, data source) ── A/ALIAS ─▶ EC2 (small, always-on, EIP)
                                                      │ Docker stack via CodeDeploy agent
GitHub push (main) ─▶ CodePipeline ─▶ CodeBuild ─▶ ECR (images)
                                          │
                                          └──▶ CodeDeploy ─▶ EC2 (pull + compose up)
SSM Parameter Store (SecureStrings): master key, DB creds, broker creds, etc.
IAM: instance profile (ECR pull, SSM read, CodeDeploy), pipeline/build/deploy roles.
VPC/subnet/SG: 443+80 inbound from internet; 22 restricted; egress open.
```

- **Networking:** a VPC (or default-VPC + SG, TDD-acceptable for a single host) with a
  security group allowing 80/443 from the internet and SSH from a restricted CIDR.
  Elastic IP on the instance so the Route 53 record is stable.
- **EC2:** one small instance (e.g. t3.small/t4g.small class), always-on, Docker +
  Docker Compose + the CodeDeploy agent installed via user-data/AMI bootstrap.
- **ECR:** one repository per image (frontend/nginx, core) or a single multi-image repo.
- **CodePipeline:** source = GitHub `main` (via a CodeStar/GitHub connection — the
  one-time interactive authorization is a sanctioned manual bootstrap); build =
  CodeBuild; deploy = CodeDeploy to the EC2 deployment group.
- **CodeBuild:** builds images, tags them (e.g. with the commit SHA), pushes to ECR.
- **CodeDeploy:** `appspec.yml` + lifecycle hook scripts that, on the instance, log in
  to ECR, pull the new tags, run the migrate/seed step, and `docker compose up -d`.
- **Route 53:** the hosted zone for `joeyshub.com` is a **data source** (never created);
  Terraform adds the `policyflow` record pointing at the EIP.
- **SSM Parameter Store:** Terraform creates the parameter *resources*; the *values*
  are injected out-of-band (CLI/console) and read by the stack at boot. They never
  appear in repo, Terraform code, or state.
- **TLS:** certbot obtains/renews a Let's Encrypt cert for `policyflow.joeyshub.com`;
  nginx terminates TLS. Renewal runs inside the stack (scheduled), honoring the
  no-host-cron rule.

### 5.4 Interfaces (P0.1 surface)

- `GET /api/health` → `200 {"status":"ok","version":"<sha>","checks":{"db":"ok","broker":"ok"}}`.
  Used by the exit test and container health checks.
- SPA routes (placeholder): `/` (landing), `/select-tenant` (tenant selection). Static,
  content replaced in P1.6. Every element carries an `id` per CLAUDE.md.
- No domain API, no auth, no events.

### 5.5 Primary flow — the deploy path (sequence)

1. Developer pushes to `main` on GitHub.
2. The GitHub connection triggers CodePipeline (Source stage).
3. CodeBuild builds the frontend + core images, tags with the commit SHA, pushes to ECR.
4. CodeDeploy runs on the EC2 host: hooks pull the new images, run Alembic
   migrate + seed (empty baseline in P0.1), then `docker compose up -d`.
5. nginx serves the new SPA + proxies the new core; the cert is already present/renewed.
6. The change is visible at `https://policyflow.joeyshub.com` — **no manual steps**.

### 5.6 Local flow (single command)

`docker compose up` (with the override for dev ergonomics) brings up Postgres,
RabbitMQ, core (Alembic runs the empty baseline), frontend, and nginx; the app is
reachable locally over HTTP. Same images/topology as prod, minus the EC2/TLS layer.

### 5.7 Diagram

Deploy pipeline + runtime topology:
[tdd-P0.1-deploy-and-topology.excalidraw](./diagrams/tdd-P0.1-deploy-and-topology.excalidraw)
([rendered PNG](./diagrams/tdd-P0.1-deploy-and-topology.png)). The ASCII in §5.2 / §5.3
remains the inline reference.

## 6. Decisions

| Decision | Chosen | Alternatives considered | Rationale |
|---|---|---|---|
| Treat the work as a program | Program & Phase Plan + scope this TDD to Phase 0 | One monolithic TDD over all 5 phases | Requirements self-decompose into Phase 0–4 with go/no-go points; monolithic TDD would be unreviewable and premature. |
| Message broker | **RabbitMQ** | Redis Streams, Kafka/Redpanda, NATS JetStream | Native exchange fan-out, per-queue DLX/DLQ, management-UI queue depth — direct fit for the event requirements; light enough for one EC2. |
| Database | **PostgreSQL** | MySQL/MariaDB | First-class schema namespaces + per-schema roles cleanly support the committed **schema-per-tenant** isolation (one schema per tenant + shared `platform` schema); strong ecosystem and FastAPI/SQLAlchemy support. |
| TLS termination | **Let's Encrypt / certbot at nginx** | ACM + ALB, imported/self-managed cert | Free auto-renewing cert at the single nginx entry; no ALB keeps the footprint to one cheap EC2. |
| Image build & delivery | **CodeBuild → ECR, CodeDeploy pulls** | Build on the EC2 host | Immutable artifacts, clean rollback, build decoupled from prod host — production-minded. |
| Deploy trigger branch | **`main`** | dedicated `release` branch | Simplest; matches single-environment (local-only dev) model; prod pushes stay at author's discretion. |
| P0 placeholder strategy | **Thin real shell, throwaway content** | Fully disposable static placeholders | Maximizes reuse of the SPA shell + core skeleton into P1; only copy is thrown away. |
| Migration tooling timing | **Wire Alembic + deploy hook now (empty baseline)** | Defer to P1 | Proves the hands-off migrate-on-deploy guarantee via the exit test instead of deferring the risk. |

## 7. Risks and Open Questions

- **TLS on a single EC2 without an ALB (Risk #2).** certbot HTTP-01 needs port 80
  reachable during issuance/renewal; if issuance fails, fall back to ACM+ALB (accepting
  cost). *Mitigation:* validate cert issuance as part of the exit test.
- **GitHub connection bootstrap.** The CodeStar/GitHub connection authorization is a
  sanctioned one-time manual step Terraform cannot fully perform; document it.
- **EC2 resource pressure.** Postgres + RabbitMQ + two app containers + nginx on a small
  instance — confirm headroom; bump instance class if the stack is starved.
- **Open question (defer to epic time):** single multi-image ECR repo vs one repo per
  image; default-VPC + SG vs a dedicated VPC. Both are low-risk and decided in the
  epic plan.
- **Open question:** exact instance class (t3.small vs t4g.small/arm) — pick at epic
  time based on image arch; keep "small/inexpensive" intact.

## 8. Rollout / Verification

**Manual verification (local):**
1. `docker compose up` → all five services healthy.
2. `GET http://localhost/api/health` → `200` with db + broker `ok`.
3. Browser: `/` shows placeholder landing; `/select-tenant` shows placeholder selection.

**Exit test (production — the acceptance gate):**
1. Make a trivial visible change (e.g. landing placeholder text), push to `main`.
2. Observe CodePipeline → CodeBuild → ECR → CodeDeploy complete with no manual steps.
3. Confirm the change is live at `https://policyflow.joeyshub.com` over valid HTTPS.

**Rollout considerations:** DB reset on deploy is acceptable pre-go-live; no data must
survive. Migrations + seed are deploy steps. Rollback = redeploy a prior ECR image tag.
Backwards compatibility is N/A (greenfield).

## 9. Work Breakdown

Ordered simplest-first; thin walking skeleton first, then the cloud path. Each item is
narrow and independently reviewable (the epic plan will refine into ~150-line epics).

1. **Repo scaffold + compose base.** Repository layout (frontend/, core/, infra/,
   ops/), `docker-compose.yml` with health-checked **PostgreSQL** + **RabbitMQ** only;
   `.env.example`. Verify both come up locally.
2. **FastAPI core skeleton.** `core/` FastAPI app, `GET /api/health` (checks DB +
   broker), Dockerfile, added to compose. Verify health returns `ok` locally.
3. **Alembic empty baseline + migrate hook.** Wire Alembic with an empty baseline
   migration and a boot/deploy migrate(+seed placeholder) entrypoint. Verify it runs
   cleanly on `up`.
4. **React SPA shell + nginx (local).** `frontend/` React app (build → static),
   `nginx` service as sole entry serving SPA + proxying `/api/`. Verify the app loads
   locally through nginx and reaches the API.
5. **Placeholder landing + tenant-selection pages `[UI]`.** Minimal landing and
   tenant-selection routes per the UI/UX Guide, every element with an `id`. Throwaway
   content; real shell.
6. **Terraform baseline: network + EC2 + IAM + SSM.** VPC/SG (80/443/restricted-22),
   EC2 (small, always-on, EIP, Docker + CodeDeploy agent), instance profile, SSM
   parameter *resources* (values out-of-band). Apply and reach the host.
7. **Terraform pipeline: ECR + CodePipeline + CodeBuild + CodeDeploy.** Repos, pipeline
   from `main`, build spec (build/push images), deployment group + roles. (GitHub
   connection authorized via the documented one-time bootstrap.)
8. **Route 53 record + certbot TLS at nginx.** Add the `policyflow.joeyshub.com` record
   (zone as data source); certbot issuance + in-stack renewal; nginx terminates TLS.
9. **CodeDeploy appspec + migrate/seed-on-deploy; prove the exit test.** `appspec.yml`
   + lifecycle hooks (ECR login, pull, migrate, `compose up`). Push a change to `main`
   and confirm it appears at the production URL with **zero manual steps** (the go/no-go
   gate).
