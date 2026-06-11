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

## Not here yet

- CodeDeploy `appspec.yml` and lifecycle hook scripts that run on the host during
  deploys (ECR login, image pull, migrate/seed, compose restart) land in Epic 11.
