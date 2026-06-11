# Walking Skeleton & Deployment Pipeline (P0.1) — Epic Plan

Source TDD: [./tdd-P0.1-walking-skeleton.md](./tdd-P0.1-walking-skeleton.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project.

> This is a high-level agile roadmap. Each epic's design specifics are confirmed
> with stakeholders at epic time (`3-plan-epic`) before any code is written.

The build proceeds in two layers: first a **thin walking skeleton that runs locally**
(epics 1–5), then the **cloud delivery path** that carries it to production (epics
6–12). The final epic proves the hands-off push→build→deploy→live exit test that is
this phase's go/no-go gate.

## Epic 1 — Repo scaffold + compose base — **COMPLETED**
- **Goal:** A single-command local stack that brings up health-checked PostgreSQL and RabbitMQ, with the repository layout and example environment in place for everything that follows.
- **Rough scope:** Repository directory layout (frontend/core/infra/ops), `docker-compose.yml` with Postgres + RabbitMQ as internal services, `.env.example`. No application containers yet.
- **Open questions / decisions for stakeholders:** Single multi-image ECR repo vs one repo per image (decided here so layout matches); final directory names.
- **Depends on:** none.
- **Implementation notes:**
  - ECR strategy: one repo per image (`policyflow-core`, `policyflow-frontend`) — fixes Epic 8's buildspec/tags and IAM scoping.
  - Top-level layout: `frontend/ core/ infra/ ops/`, each with a placeholder `README.md` naming what lands there and in which epic.
  - Added a top-level `README.md` beyond the plan: monorepo overview plus `cp .env.example .env` + `docker compose up` run instructions.
  - `docker-compose.override.yml` deferred until app containers exist (Epic 2/4) — nothing to override yet.
  - Both services are internal-only (no `ports:`) for local/prod parity, on a single named bridge network `policyflow-internal`, each with a named volume and a container healthcheck.
  - No deprecated top-level `version:` key in `docker-compose.yml`.
  - `.gitignore` keeps the pre-existing `.claude/` rule and adds `.env` plus standard Python/Node/Terraform noise; `.env.example` is the committed template, real `.env` never committed.
  - Verified locally: `docker compose config` parses; `docker compose up -d` brought both services to `healthy`; `docker compose ps` showed only internal container ports (no host publishing); torn down with `docker compose down -v`.

## Epic 2 — FastAPI core skeleton + health check — **COMPLETED**
- **Goal:** The `core` FastAPI service runs in the stack and exposes `GET /api/health` that reports DB and broker reachability.
- **Rough scope:** `core/` FastAPI app, health endpoint with DB + broker checks, Dockerfile, wired into compose with a container health check.
- **Open questions / decisions for stakeholders:** Health payload shape (`status`/`version`/`checks`) and how `version` is sourced (commit SHA injection).
- **Depends on:** Epic 1.
- **Implementation notes:**
  - Payload shape: `{"status","version","checks":{"db","broker"}}` (TDD §5.4, no `time` field). All checks ok → `200` `status:"ok"`; any check fails → `503` `status:"degraded"` with the failing check marked `"error"`, which drives the container health check `unhealthy`.
  - `version` source: Dockerfile `ARG GIT_SHA=dev` → `ENV APP_VERSION`, read by `config.py`; defaults to `dev` locally. Epic 8 CodeBuild injects the real short SHA via `--build-arg`. No git access at runtime.
  - Base `python:3.12-slim` + `uvicorn`; DB probe via `asyncpg.connect` + `SELECT 1`; broker probe via `aio_pika.connect`/close (real AMQP handshake). Each probe wrapped so a failure reports `"error"` rather than crashing the endpoint.
  - `DATABASE_URL` / `RABBITMQ_URL` / `GIT_SHA` composed in `docker-compose.yml` from existing `POSTGRES_*` / `RABBITMQ_*` vars — `.env.example` unchanged. `GIT_SHA` defaults to `dev` via `${GIT_SHA:-dev}`.
  - `core` service has no host `ports:` (parity; nginx is the sole entry, Epic 4). Healthcheck curls `localhost:8000/api/health` with the same interval/timeout/retries/start_period style as Epic 1. `curl` installed in the image for it.
  - Pinned deps: `fastapi==0.115.6`, `uvicorn[standard]==0.34.0`, `asyncpg==0.30.0`, `aio-pika==9.5.4`. Added `core/.dockerignore`.
  - Verified locally end-to-end: `docker compose config` parses with no host port on `core`; `docker compose up -d --build` brought all three services `healthy`; endpoint returned `200 {"status":"ok","version":"dev","checks":{"db":"ok","broker":"ok"}}`; stopping postgres flipped the body to `503` `degraded` `db:"error"` and drove `core` `unhealthy`; restarting postgres returned it to `ok`/`healthy`; torn down with `docker compose down -v`.

## Epic 3 — Alembic empty baseline + migrate-on-boot hook — **COMPLETED**
- **Goal:** Migrations are wired with an empty baseline and run automatically as a boot/deploy step — proving the hands-off migrate-on-deploy seam early.
- **Rough scope:** Alembic config in `core/`, one empty baseline migration, an entrypoint/hook that runs migrate (plus a seed placeholder) before the app serves.
- **Open questions / decisions for stakeholders:** Where the seed placeholder hook lives; behavior on migrate failure (fail boot vs degrade).
- **Depends on:** Epic 2.
- **Implementation notes:**
  - Decisions: migrate failure → **fail boot** (`set -e` in `core/entrypoint.sh`); seed placeholder → **`core/app/seed.py`**, run via `python -m app.seed` from the entrypoint after migrate.
  - Entrypoint order is migrate → seed → uvicorn inside the core container (no separate compose service); `ENTRYPOINT ["./entrypoint.sh"]` exec's the existing `CMD` (uvicorn). Epic 11 reuses the same `alembic upgrade head`.
  - Sync migrations via `psycopg[binary]`; `env.py` rewrites the asyncpg-style `DATABASE_URL` scheme (`postgres://` / `postgresql://`) to `postgresql+psycopg://`. The async `asyncpg` health probe in `health.py` is untouched.
  - Empty baseline (`0001_empty_baseline.py`, `down_revision=None`, `pass` bodies) — only the `alembic_version` table is created; real schema arrives P1+.
  - `alembic.ini` leaves `sqlalchemy.url` blank (supplied by `env.py` from the environment); `target_metadata = None` (no models yet). Standard `script.py.mako` template added for future revisions.
  - Pinned: `alembic==1.14.0`, `psycopg[binary]==3.2.3`. Dockerfile copies `alembic.ini`, `alembic/`, and `entrypoint.sh` (made executable); `.dockerignore` excludes neither.
  - Verified locally end-to-end: `docker compose config` parses; `docker compose up -d --build` brought all three services `healthy`; core logs showed `Running upgrade  -> 0001_empty_baseline` then the seed placeholder line before uvicorn; `psql \dt` showed only `alembic_version` with `version_num=0001_empty_baseline`; `/api/health` returned `200 {"status":"ok",…}`; a second `alembic upgrade head` was a no-op (idempotent); torn down with `docker compose down -v`.
  - Review fix: added a repo-root `.gitattributes` pinning `*.sh` (and `core/alembic/script.py.mako`) to `eol=lf` so `core.autocrlf=true` on Windows checkouts can't rewrite `entrypoint.sh` to CRLF and bake a `bad interpreter` into the Linux image.
  - Review fix (defense-in-depth): `ENTRYPOINT ["/bin/sh", "./entrypoint.sh"]` so a stray CR in the shebang can't break interpreter resolution.
  - Review fix (fail-boot consistency): `env.py:get_synchronous_database_url()` now raises a clear `RuntimeError` on a missing/unsupported `DATABASE_URL` scheme instead of returning a blank/raw URL, so a misconfigured deploy fails fast.

## Epic 4 — nginx as sole entry + React SPA shell (local) — **COMPLETED**
- **Goal:** A React app builds to static assets served by nginx, with nginx as the single entry point reverse-proxying `/api/*` to core — reachable end-to-end locally over HTTP.
- **Rough scope:** `frontend/` React build, `nginx` service serving the SPA + proxying the API, compose wiring; local dev ergonomics (hot reload) confined to the override file.
- **Open questions / decisions for stakeholders:** Prod static-serving mechanism (assets copied into the nginx image vs shared volume); whether the override runs the Vite dev server.
- **Depends on:** Epic 2.
- **Implementation notes:**
  - Stakeholder decisions honored: prod static-serving → **baked into the nginx image** (multi-stage `frontend/Dockerfile`: `node:20-alpine` build → `nginx:1.27-alpine` runtime with `dist/` copied in); **one `frontend` service is the nginx image** (collapses the TDD "frontend"/"nginx" boxes into the single `policyflow-frontend` image, matching Epic 1's two-image ECR decision).
  - **Vite dev server deferred** — no `docker-compose.override.yml` this epic; default `docker compose up --build` runs the exact prod-parity path (nginx serving the build). Rebuild the image to see changes; hot reload lands Epic 5 / P1.6.
  - `frontend` is the **sole published host port** (`80:80`); `core` keeps no host port (parity unchanged). `depends_on: core` (`condition: service_healthy`), on `policyflow-internal`, same interval/timeout/retries/start_period style as the existing services.
  - SPA fallback `try_files $uri $uri/ /index.html`; `/api/` reverse-proxies to `core:8000` with `Host`/`X-Real-IP`/`X-Forwarded-For`/`X-Forwarded-Proto` headers.
  - **Fix (nginx boot):** `proxy_pass` to a static `core:8000` made nginx resolve the upstream at startup and crash with `host not found in upstream "core"`. Resolved by adding `resolver 127.0.0.11` (Docker DNS) + holding the upstream in a `set $core_upstream` variable so resolution is deferred to request time. The full `/api/health` URI is preserved (upstream has no path), which is what core expects.
  - **Fix (healthcheck):** nginx `listen 80;` is IPv4-only, but `localhost` inside the alpine image resolves to `::1` first, so a `localhost` healthcheck was refused → `unhealthy`. Pointed the container healthcheck at `http://127.0.0.1/` (busybox `wget --spider`).
  - Stack: TypeScript React via Vite (pinned deps + committed `package-lock.json` so the image's `npm ci` is reproducible). Throwaway shell only (heading + subtitle + a small typed `getHealth()` helper and `HealthStatus` component that fetches `/api/health` on load with loading/error/success states) — no router, no state library, no Guide styling (Epic 5 owns those). Every rendered element carries a descriptive `id`.
  - Verified locally end-to-end: `npm install` + `npm run build` produced `frontend/dist/` (`index.html` + hashed JS); `docker compose up -d --build` brought all four services `healthy`; `http://localhost/` served the SPA (bundle references `/api/health` + shell copy); `curl http://localhost/api/health` → `200 {"status":"ok","version":"dev","checks":{"db":"ok","broker":"ok"}}` proxied through nginx; `docker compose ps` showed only `frontend` publishing a host port (`:80`), `core` none; `docker compose down -v` torn down cleanly.

## Epic 5 — Placeholder landing + tenant-selection pages [UI] — **COMPLETED**
- **Goal:** Minimal landing (`/`) and tenant-selection (`/select-tenant`) routes render through the SPA shell, following the UI/UX Guide, every element carrying an `id`.
- **Rough scope:** Two placeholder routes/components with throwaway content on the real shell. No real tenant data or selection logic.
- **Open questions / decisions for stakeholders:** How much of the real visual language to apply now vs defer to P1.6; routing approach for the two pages.
- **Depends on:** Epic 4.
- **Implementation notes:**
  - **Routing (Phase 1):** `react-router-dom` pinned to `6.30.4` (latest v6); `npm install` refreshed `package-lock.json` (image build runs `npm ci`). `main.tsx` wraps `<App>` in `BrowserRouter`; `App.tsx` holds the route table — `/` → `LandingPage`, `/select-tenant` → `SelectTenantPage`, catch-all `*` → `<Navigate to="/" replace />`. Inter-page navigation uses `<Link>` so it stays client-side.
  - **Throwaway removed:** deleted `src/HealthStatus.tsx` + `src/getHealth.ts` (Epic 4 proof-of-proxy); the `/api/health` proxy itself is untouched and still verified live below.
  - **Tokens (Phase 2):** added `src/styles/tokens.css` with only the foundational `:root` subset used by these pages (surfaces `0/1/2/3`, `--on-surface`/`-variant`, `--outline`/`-strong`, `--space-1..7`, `--radius-sm/md`, display/ui/mono fonts, motion, focus ring) — values copied verbatim from the Guide. Tenant brand + persona ramps and the component-library tokens are deliberately deferred to P1.6 (no tenant selected → tenant-colored chrome is N/A). Mono is a CSS fallback stack only; no mono web font is loaded.
  - **Base styling (Phase 2):** `src/styles/base.css` — paper `--surface-0` canvas, `--font-ui` body, `font-variant-numeric: tabular-nums`, a global `:focus-visible` ring, and a `prefers-reduced-motion` opacity-only rule. Added a small `box-sizing: border-box` + margin reset (not spelled out in the plan, but needed so the paper canvas fills the viewport cleanly). All three style files imported at the top of `main.tsx`.
  - **Fonts (Phase 2):** Besley (600) + Public Sans (400/500/600) loaded via Google Fonts `<link>` in `index.html` with `preconnect` to googleapis + gstatic; every new `<link>` carries an `id`.
  - **Layout + editorial styling (Phase 3):** extracted a small `PageLayout` component (tenant-agnostic paper header with the Besley wordmark + hairline rule, wrapping a centered ~1280px `main`) shared by both pages. It takes a `pageId` prop so each page's layout elements get unique hierarchical ids (e.g. `landing-header`, `select-tenant-main`). Landing = Besley Display hero + Oxford double rule + Public Sans subtitle + one Tonal button → `/select-tenant`. Select-tenant = Besley Headline + two flat bordered Cards (Sunshine Senior Benefits / Florida Family Planning, names + a placeholder note, no selection logic) + a Text back link → `/`. Page styles live in `src/styles/pages.css`, tokens only — no raw hex/spacing outside the token set.
  - **IDs:** every rendered element carries a unique kebab-case `{page}-{element}` id (CLAUDE.md); CSS class names drive styling, ids stay reserved for targeting.
  - **Verified end-to-end:** `npm install` + `npm run build` clean under strict / `noUnusedLocals` (39 modules, ~0.93 kB html + 3.63 kB css + 166.7 kB js). `docker compose up -d --build` brought all four services `healthy` with only `frontend` publishing `:80`; `GET /` → `200` serving the SPA (references the hashed bundle), `GET /select-tenant` deep link → `200` via the nginx `try_files` fallback (serves `index.html`), `GET /api/health` → `200 {"status":"ok","version":"dev","checks":{"db":"ok","broker":"ok"}}` proxied untouched. Torn down with `docker compose down -v`.
  - **Review nits (Approve with nits — non-blocking, revisit in P1.6):** (1) the masthead wordmark is sized 20px/28px, which is off the Guide §3 type scale (no 20px role) — could snap to Title 18/24. (2) the landing button fills with `--surface-3` rather than the Guide §5 Tonal `--primary-container` (recorded decision: no tenant selected yet → no tenant ramp); it currently reads closer to an Outlined button — revisit as a true Tonal once tenant ramps exist. (3) the Oxford double rule is approximated with `border-top`/padding/`border-bottom` on a zero-height `<hr>` — worth a render check at 125%/150% fractional scaling (Guide §7 QA). No frontend test suite exists yet (pre-existing walking-skeleton gap), so no automated tests cover these pages.

## Epic 6 — Terraform network + EC2 host — **COMPLETED**
- **Goal:** Terraform provisions the network and a small always-on EC2 host with a stable Elastic IP, Docker, and the CodeDeploy agent — reachable and ready to run the stack.
- **Rough scope:** VPC/SG (or default-VPC + SG) allowing 80/443 from the internet and restricted SSH, EC2 instance with EIP, user-data/AMI bootstrap for Docker + CodeDeploy agent.
- **Open questions / decisions for stakeholders:** Default-VPC + SG vs dedicated VPC; instance class (t3.small vs t4g.small/arm — keep "small/inexpensive"); restricted SSH CIDR.
- **Depends on:** Epic 1 (stack definition the host will run).
- **Implementation notes:**
  - **Network:** default VPC + a Terraform-managed security group. The default VPC and its subnets are read as data sources (`data.tf`), never created. SG (`network.tf`): ingress 80 + 443 from `0.0.0.0/0`, ingress 22 from the required `ssh_ingress_cidr`, egress all.
  - **Instance:** `t3.small` (x86_64), AL2023 AMI resolved from the public SSM parameter `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` (no hard-coded AMI id). Placed in `data.aws_subnets.default.ids[0]`, 30 GiB encrypted gp3 root volume. `aws_eip` + `aws_eip_association` give a stable public IP (`ec2.tf`).
  - **No instance profile / SSM (Epic 7):** the instance ships with no IAM instance profile. `user-data.sh` installs the CodeDeploy agent *binary* (Ruby + the region install script); it stays idle until Epic 7/9 grant a role + deployment group. User-data is `#!/bin/bash` + `set -euo pipefail`, installs/enables Docker, installs the Docker Compose v2 CLI plugin into the docker cli-plugins dir, adds `ec2-user` to `docker`, and is written idempotent.
  - **State:** S3 backend + DynamoDB lock, enabled by a separate `infra/bootstrap/` config with local state (versioned + SSE + public-access-blocked bucket, PAY_PER_REQUEST lock table). Region is `var.region` defaulting to `us-east-1`. Provider sets `default_tags { Project = "policyflow" }`; AWS provider `~> 5`.
  - **SSH safety:** `ssh_ingress_cidr` is required with **no default**, so an apply cannot silently open port 22 to the world. `terraform.tfvars.example` carries a placeholder (`203.0.113.4/32`, TEST-NET-3) with a comment to replace it. `.gitignore` now ignores real `*.tfvars` while keeping `*.tfvars.example`; `.terraform.lock.hcl` stays committed.
  - **Outputs:** `public_ip` (EIP), `instance_id`, `security_group_id`.
  - **Verification (local, no apply — apply needs credentials and costs money):** `terraform fmt -recursive infra/` clean (it fixed alignment in `bootstrap/main.tf`); `terraform init -backend=false` + `terraform validate` pass for both `infra/` and `infra/bootstrap/`. No `plan`/`apply` run; the README documents the manual bootstrap → init → apply hand-off.
  - **Sizing:** ~14 files / ~430 changed lines, over the ~8-file/~150-line budget, but it is all Terraform config + bootstrap scaffolding (explicitly discounted by the conventions) and a network+host baseline is an atomic unit (the original TDD item was already split into Epic 6 here + Epic 7 for IAM/SSM). Kept whole — one focused concern.
  - **Review (Approve with nits — non-blocking, carry forward):** (1) `subnet_id = data.aws_subnets.default.ids[0]` selects a subnet by list index, whose order is not guaranteed stable — a later apply could pick a different AZ and force instance replacement; pin the AZ/subnet explicitly if that matters (low risk for one always-on host). (2) `user-data.sh` header comment mentions `$${region}` (the escaped/literal form) where the real template variable is `${region}` — comment wording only, code is correct. (3) `COMPOSE_VERSION` is intentionally pinned and will age (CodeDeploy agent installs `latest`). (4) the bootstrap state bucket has no noncurrent-version expiration lifecycle rule, so old state versions accumulate. None block; revisit as housekeeping.

## Epic 7 — Terraform IAM instance profile + SSM secrets seam — **COMPLETED**
- **Goal:** The host can pull from ECR, read SSM, and act with CodeDeploy via an instance profile; SSM SecureString parameter *resources* exist for the stack's secrets (values injected out-of-band).
- **Rough scope:** IAM instance profile + policies attached to the EC2 host; SSM Parameter Store resource definitions (no values in code/state); stack reads them at boot.
- **Open questions / decisions for stakeholders:** Exact parameter naming/paths; least-privilege policy boundaries.
- **Depends on:** Epic 6.
- **Implementation notes:**
  - **New `infra/iam.tf`:** `aws_iam_role.host` (EC2 `sts:AssumeRole` trust via `data.aws_iam_policy_document`) + `aws_iam_instance_profile.host`, attached to `aws_instance.host` in `ec2.tf` (in-place update, no replacement). Two inline `aws_iam_role_policy` resources, each from a policy document.
  - **Policy scope (stakeholder decision):** custom **inline** policies scoped by **ARN prefix**, not AWS-managed. ECR pull = `ecr:GetAuthorizationToken` on `*` (token call can't be resource-scoped) + layer/image reads scoped to `arn:aws:ecr:${region}:${account}:repository/${project_name}-*`. SSM read = `ssm:GetParameter(s)`/`GetParametersByPath` scoped to `parameter/${project_name}/*`.
  - **KMS-via-SSM condition:** `kms:Decrypt` on `*` gated by `kms:ViaService = ssm.${region}.amazonaws.com`, so SecureStrings decrypt through SSM (incl. the AWS-managed `aws/ssm` key) without naming a key ARN, and nothing else.
  - **SSM params (stakeholder decision):** DB + broker passwords only — `/policyflow/postgres/password`, `/policyflow/rabbitmq/password`. No master key (deferred). `infra/ssm.tf` creates them via `for_each` over a `local.host_secret_parameters` (path => Name-tag) map.
  - **ignore_changes / out-of-band placeholder pattern:** each parameter ships a non-secret `"CHANGE_ME"` placeholder with `lifecycle { ignore_changes = [value] }`; real values set out-of-band via `aws ssm put-parameter --type SecureString --overwrite` (documented in README), so secrets never enter repo, code, or state.
  - **Deferred S3 grant:** CodeDeploy's S3 artifact read is **deferred to Epic 9** (where the bucket is created). Epic 7 grants ECR + SSM only — no S3 permissions added.
  - **Other edits:** `data.tf` gains `aws_caller_identity.current` (account id for ARNs); `outputs.tf` gains `iam_instance_profile_name` + `ssm_parameter_names`; `user-data.sh` CodeDeploy comment updated (Epic 7 now supplies the profile, deployment group still in Epic 9 — comment only, no logic change); README documents `iam.tf`/`ssm.tf`, moves IAM/SSM out of "Not here yet", and adds the value-injection step.
  - **Verification (local, no apply):** `terraform fmt -recursive infra/` clean (no reformatting); `cd infra && terraform init -backend=false && terraform validate` → "The configuration is valid." `infra/bootstrap` untouched.

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
