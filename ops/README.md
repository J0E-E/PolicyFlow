# ops

CI/CD recipe files used by the AWS build and deploy services.

## What is here today (Epic 8 — CodeBuild buildspec)

- `buildspec.yml` — the CodeBuild recipe (referenced by `infra/codebuild.tf` via
  `source.buildspec`). It derives the short commit SHA, logs Docker in to ECR,
  builds the core + frontend images, tags each with `:<short-sha>` and `:latest`,
  and pushes them. The ECR repository URLs and region are supplied as CodeBuild
  environment variables, so no account id is hard-coded. Epic 9's pipeline reuses
  this same buildspec unchanged.

## What is here today (Epic 10 — one-time TLS issuance bootstrap)

- `init-letsencrypt.sh` — a **one-time** Let's Encrypt issuance bootstrap, run by
  hand on the host after DNS resolves to the EIP (a sanctioned manual step, like
  authorizing the GitHub connection). It reads `CERTBOT_DOMAIN` / `CERTBOT_EMAIL` /
  `CERTBOT_STAGING` from `.env`, downloads certbot's recommended
  `options-ssl-nginx.conf` + `ssl-dhparam.pem` into the `letsencrypt` volume,
  creates a throwaway self-signed dummy cert so nginx can boot, starts the prod
  `frontend`, deletes the dummy, requests the real cert over HTTP-01
  (`--staging` when `CERTBOT_STAGING=1`), and reloads nginx onto it. After this,
  renewal is automatic via the in-stack `certbot` sidecar in
  `docker-compose.prod.yml` — there is no host cron. See `infra/README.md` →
  "TLS issuance + renewal" for the full host flow and the ACM+ALB fallback.

  ```sh
  # on the host, from the repo root, once:
  ./ops/init-letsencrypt.sh
  ```

## What is here today (Epic 11 — CodeDeploy appspec + hooks)

- `../appspec.yml` (repo root) — the CodeDeploy recipe. CodeDeploy requires it at
  the root of the deployment bundle, which is the GitHub source checkout the
  pipeline's Deploy stage feeds in. It installs the bundle to `/opt/policyflow`
  (`file_exists_behavior: OVERWRITE`, which preserves the gitignored, deploy-written
  `.env`) and maps three lifecycle events to the scripts in `deploy/`.

- `deploy/prod.env.defaults` — committed, NON-secret production defaults
  (`POSTGRES_USER`, `POSTGRES_DB`, `RABBITMQ_DEFAULT_USER`, `CERTBOT_*`). The two
  passwords and the two image refs are appended at deploy time and never appear here.

- `deploy/lib.sh` — shared seam sourced by every hook: `APP_DIR=/opt/policyflow`,
  the `COMPOSE_FILES` invocation (base + prod overlay), the region (from IMDSv2)
  and account id (from STS), and the derived ECR `REGISTRY` + `CORE_IMAGE` /
  `FRONTEND_IMAGE` (`:latest`).

- The lifecycle hooks, run by the CodeDeploy agent in this order:
  - `deploy/after_install.sh` (**AfterInstall**) — fetch the two passwords from
    SSM (`/policyflow/postgres/password`, `/policyflow/rabbitmq/password`), write
    `/opt/policyflow/.env` from `prod.env.defaults` + those secrets + the image
    refs, log Docker in to ECR, and `docker compose ... pull` the new images.
  - `deploy/application_start.sh` (**ApplicationStart**) — `docker compose ... up -d`.
    This is the migrate + seed step: core's entrypoint runs `alembic upgrade head`
    then `python -m app.seed` before serving (Epic 3), so a failed migration fails
    the boot — and therefore the deploy.
  - `deploy/validate_service.sh` (**ValidateService**) — poll core's
    `/api/health` (from inside the container; core publishes no host port) for up
    to ~2 minutes and exit non-zero if it never goes healthy, so a bad boot fails
    the deployment instead of leaving a broken host.

  No `ApplicationStop` hook: the first deploy has no prior revision, and `up -d`
  recreates only the containers whose image or config changed.

### Privileged DB roles need no deploy-time creds

`demo_purge` (and the older `outbox_relay` / `audit_writer`) are `NOLOGIN`
roles — they have no password and cannot connect. A migration `GRANT`s each to
the single login role, which reaches them at runtime via `SET LOCAL ROLE`. The
`demo_purge` grant ships in migration `0013`, and migrations run on every deploy
(core's entrypoint runs `alembic upgrade head` in `application_start.sh`, above),
so the role is wired the moment the deploy migrates. There are therefore **no
per-role passwords in SSM/Terraform for any privileged role** — `after_install.sh`
fetches only the two service-account passwords (`postgres`, `rabbitmq`). Adding a
privileged role is a migration change, never a deploy-config one.

### One-time host bootstrap order

The deploy regenerates `/opt/policyflow/.env` on every run, so there is nothing to
place by hand for it. TLS issuance is **automatic on the first deploy**:
`application_start.sh` self-issues the cert (dummy cert → `up -d` → certbot →
reload) when none exists yet and no-ops once a real cert is present, so no host
step is required; `init-letsencrypt.sh` (above) stays as a manual fallback. For the
full ordered bring-up and the live end-to-end proof (push → Build → ECR → Deploy
swaps the stack, migrate runs, site live over HTTPS), see `exit-test-runbook.md`.

## The live proof runbook (Epic 12 — go/no-go gate)

- `exit-test-runbook.md` — orchestrates the one-time bring-up across the existing
  per-step docs into the correct end-to-end order (including the cert/image/volume
  ordering the first HTTPS deploy hits), defines the steady-state exit test, and
  records the live pass/fail result. It points to the per-step docs rather than
  restating them.
