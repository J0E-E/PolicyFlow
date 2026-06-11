# ops

CI/CD recipe files used by the AWS build and deploy services.

## What is here today (Epic 8 — CodeBuild buildspec)

- `buildspec.yml` — the CodeBuild recipe (referenced by `infra/codebuild.tf` via
  `source.buildspec`). It derives the short commit SHA, logs Docker in to ECR,
  builds the core + frontend images, tags each with `:<short-sha>` and `:latest`,
  and pushes them. The ECR repository URLs and region are supplied as CodeBuild
  environment variables, so no account id is hard-coded. Epic 9's pipeline reuses
  this same buildspec unchanged.

## Not here yet

- CodeDeploy `appspec.yml` and lifecycle hook scripts that run on the host during
  deploys (ECR login, image pull, migrate/seed, compose restart) land in Epic 11.
