# Walking Skeleton & Deployment Pipeline (P0.1) — Epic Plan

Source TDD: [./tdd-P0.1-walking-skeleton.md](./tdd-P0.1-walking-skeleton.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project.

> This is a high-level agile roadmap. Each epic's design specifics are confirmed
> with stakeholders at epic time (`3-plan-epic`) before any code is written.

The build proceeds in two layers: first a **thin walking skeleton that runs locally**
(epics 1–5), then the **cloud delivery path** that carries it to production (epics
6–12). The final epic proves the hands-off push→build→deploy→live exit test that is
this phase's go/no-go gate.

## Epic 1 — Repo scaffold + compose base
- **Goal:** A single-command local stack that brings up health-checked PostgreSQL and RabbitMQ, with the repository layout and example environment in place for everything that follows.
- **Rough scope:** Repository directory layout (frontend/core/infra/ops), `docker-compose.yml` with Postgres + RabbitMQ as internal services, `.env.example`. No application containers yet.
- **Open questions / decisions for stakeholders:** Single multi-image ECR repo vs one repo per image (decided here so layout matches); final directory names.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 2 — FastAPI core skeleton + health check
- **Goal:** The `core` FastAPI service runs in the stack and exposes `GET /api/health` that reports DB and broker reachability.
- **Rough scope:** `core/` FastAPI app, health endpoint with DB + broker checks, Dockerfile, wired into compose with a container health check.
- **Open questions / decisions for stakeholders:** Health payload shape (`status`/`version`/`checks`) and how `version` is sourced (commit SHA injection).
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 3 — Alembic empty baseline + migrate-on-boot hook
- **Goal:** Migrations are wired with an empty baseline and run automatically as a boot/deploy step — proving the hands-off migrate-on-deploy seam early.
- **Rough scope:** Alembic config in `core/`, one empty baseline migration, an entrypoint/hook that runs migrate (plus a seed placeholder) before the app serves.
- **Open questions / decisions for stakeholders:** Where the seed placeholder hook lives; behavior on migrate failure (fail boot vs degrade).
- **Depends on:** Epic 2.
- **Implementation notes:** _none yet_

## Epic 4 — nginx as sole entry + React SPA shell (local)
- **Goal:** A React app builds to static assets served by nginx, with nginx as the single entry point reverse-proxying `/api/*` to core — reachable end-to-end locally over HTTP.
- **Rough scope:** `frontend/` React build, `nginx` service serving the SPA + proxying the API, compose wiring; local dev ergonomics (hot reload) confined to the override file.
- **Open questions / decisions for stakeholders:** Prod static-serving mechanism (assets copied into the nginx image vs shared volume); whether the override runs the Vite dev server.
- **Depends on:** Epic 2.
- **Implementation notes:** _none yet_

## Epic 5 — Placeholder landing + tenant-selection pages [UI]
- **Goal:** Minimal landing (`/`) and tenant-selection (`/select-tenant`) routes render through the SPA shell, following the UI/UX Guide, every element carrying an `id`.
- **Rough scope:** Two placeholder routes/components with throwaway content on the real shell. No real tenant data or selection logic.
- **Open questions / decisions for stakeholders:** How much of the real visual language to apply now vs defer to P1.6; routing approach for the two pages.
- **Depends on:** Epic 4.
- **Implementation notes:** _none yet_

## Epic 6 — Terraform network + EC2 host
- **Goal:** Terraform provisions the network and a small always-on EC2 host with a stable Elastic IP, Docker, and the CodeDeploy agent — reachable and ready to run the stack.
- **Rough scope:** VPC/SG (or default-VPC + SG) allowing 80/443 from the internet and restricted SSH, EC2 instance with EIP, user-data/AMI bootstrap for Docker + CodeDeploy agent.
- **Open questions / decisions for stakeholders:** Default-VPC + SG vs dedicated VPC; instance class (t3.small vs t4g.small/arm — keep "small/inexpensive"); restricted SSH CIDR.
- **Depends on:** Epic 1 (stack definition the host will run).
- **Implementation notes:** _none yet_

## Epic 7 — Terraform IAM instance profile + SSM secrets seam
- **Goal:** The host can pull from ECR, read SSM, and act with CodeDeploy via an instance profile; SSM SecureString parameter *resources* exist for the stack's secrets (values injected out-of-band).
- **Rough scope:** IAM instance profile + policies attached to the EC2 host; SSM Parameter Store resource definitions (no values in code/state); stack reads them at boot.
- **Open questions / decisions for stakeholders:** Exact parameter naming/paths; least-privilege policy boundaries.
- **Depends on:** Epic 6.
- **Implementation notes:** _none yet_

## Epic 8 — Terraform ECR + CodeBuild image build
- **Goal:** Terraform provisions image storage and a CodeBuild project that builds the frontend + core images, tags them with the commit SHA, and pushes them to ECR.
- **Rough scope:** ECR repository(ies), CodeBuild project + buildspec, build IAM role. Manually triggerable build proves images land in ECR.
- **Open questions / decisions for stakeholders:** Buildspec structure; single multi-image repo vs per-image (consistent with Epic 1); tag scheme.
- **Depends on:** Epic 7 (registry permissions), and the buildable images from Epics 2 + 4.
- **Implementation notes:** _none yet_

## Epic 9 — Terraform CodePipeline + CodeDeploy wiring
- **Goal:** A push to `main` on GitHub triggers a pipeline (Source → Build → Deploy) wired to the EC2 deployment group — the automated path exists end-to-end (deploy hooks land in Epic 12).
- **Rough scope:** GitHub/CodeStar connection (one-time interactive authorization documented), CodePipeline from `main`, CodeDeploy application + deployment group + roles.
- **Open questions / decisions for stakeholders:** Documenting the connection bootstrap; pipeline/role boundaries.
- **Depends on:** Epic 8.
- **Implementation notes:** _none yet_

## Epic 10 — Route 53 record + certbot TLS at nginx
- **Goal:** `policyflow.joeyshub.com` resolves to the host over valid HTTPS, with the cert auto-renewed by an in-stack scheduled job (establishing the no-host-cron scheduling seam).
- **Rough scope:** Route 53 A/ALIAS record (hosted zone as a data source, never created), certbot issuance via HTTP-01, nginx TLS termination, in-stack renewal job.
- **Open questions / decisions for stakeholders:** Renewal-job mechanism inside the stack; fallback to ACM+ALB if HTTP-01 issuance fails (Risk #2).
- **Depends on:** Epic 6 (host + EIP) and Epic 4 (nginx entry point).
- **Implementation notes:** advanced — issuance + renewal + DNS + TLS termination are a single correctness-critical unit; splitting would ship a half-configured cert. Human-approved exception.

## Epic 11 — CodeDeploy appspec + migrate/seed-on-deploy
- **Goal:** On deploy, the host logs in to ECR, pulls the new image tags, runs migrate + seed, and `docker compose up -d` — the deploy actually swaps the running stack.
- **Rough scope:** `appspec.yml` + lifecycle hook scripts under `ops/` performing ECR login, pull, migrate/seed step, and compose restart on the instance.
- **Open questions / decisions for stakeholders:** Hook ordering/lifecycle events; how the migrate step (Epic 3) is invoked during deploy; DB-reset-on-deploy handling.
- **Depends on:** Epic 9 (pipeline/deploy group) and Epic 3 (migrate hook).
- **Implementation notes:** _none yet_

## Epic 12 — Prove the exit test (go/no-go gate)
- **Goal:** A trivial visible change pushed to `main` appears at `https://policyflow.joeyshub.com` over valid HTTPS with **zero manual steps** — the phase acceptance gate.
- **Rough scope:** Make a trivial change (e.g. landing placeholder text), push, observe Source → Build → ECR → Deploy complete hands-off, confirm it is live over HTTPS. Capture any final glue/fixes the end-to-end run reveals.
- **Open questions / decisions for stakeholders:** None expected — this is verification of everything prior; any failure routes back to the relevant epic.
- **Depends on:** Epics 10 and 11.
- **Implementation notes:** _none yet_
