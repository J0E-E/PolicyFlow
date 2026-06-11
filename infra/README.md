# infra

Terraform for all AWS resources (network, EC2 host, IAM, ECR, CodeBuild,
CodePipeline, CodeDeploy, Route 53, TLS). Filled in across Epics 6–11.

## What is here today (Epics 6–10 — network, host, IAM, SSM, ECR, CodeBuild, CodePipeline, CodeDeploy, Route 53)

- `bootstrap/` — a small standalone config (with **local** state) that creates the
  S3 bucket + DynamoDB table this root config uses for remote state. See
  `bootstrap/README.md`.
- `versions.tf` — Terraform + AWS provider (`~> 5`) requirements and the `backend "s3"`
  block pointing at the bootstrap bucket/table.
- `providers.tf` — the AWS provider, region from `var.region`, `default_tags` of
  `Project = policyflow` on every resource.
- `variables.tf` — `region`, `project_name`, `instance_type`, `github_branch`
  (default `main`), `hosted_zone_name` (default `joeyshub.com`, the existing zone),
  `domain_name` (default `policyflow.joeyshub.com`, the FQDN served over HTTPS), and
  the **required** `ssh_ingress_cidr`, `source_repository_url` (the GitHub clone URL
  CodeBuild builds from), and `github_repository_id` (the `owner/repo` the
  pipeline's Source action watches).
- `data.tf` — reads the default VPC + its subnets (never created), the latest
  AL2023 x86_64 AMI from the public SSM parameter, and the current account id
  (used to build the IAM policy ARNs).
- `iam.tf` — the host's IAM role + instance profile (attached in `ec2.tf`), with
  two least-privilege inline policies: ECR pull (token on `*`, layer/image reads
  scoped to `${project_name}-*` repositories) and SSM read (parameters under
  `/${project_name}/*`, plus `kms:Decrypt` gated to SSM-only via a `kms:ViaService`
  condition), plus the CodeDeploy agent's S3 read of the deploy bundle scoped to
  the pipeline artifact bucket (added in Epic 9).
- `ecr.tf` — one ECR repository per image (`policyflow-core`, `policyflow-frontend`),
  created via `for_each` over a `local.ecr_repositories` set. Each is `MUTABLE`
  (every build pushes both an immutable `:<short-sha>` tag and a moving `:latest`
  tag) with `scan_on_push` enabled, plus a lifecycle policy expiring **untagged**
  images after 14 days.
- `codebuild.tf` — the `policyflow-build` CodeBuild project that runs
  `ops/buildspec.yml` to build the core + frontend images and push them to ECR.
  `BUILD_GENERAL1_SMALL`, AWS-managed standard Linux image, `privileged_mode`
  (Docker builds), `NO_ARTIFACTS`, source `type = "GITHUB"` at
  `var.source_repository_url`. Its IAM role mirrors `iam.tf`: ECR push scoped to
  `${project_name}-*` repositories (token on `*`) and CloudWatch Logs scoped to the
  project's `/aws/codebuild/${project_name}-build` group, plus (Epic 9) read/write
  on the pipeline artifact bucket — in pipeline mode CodeBuild downloads the Source
  input artifact from S3. The repo URLs + region are passed to the buildspec as
  `environment_variable`s.
- `artifacts.tf` — a private S3 bucket (`${project_name}-pipeline-artifacts-${account_id}`,
  account id folded in for global uniqueness) holding the pipeline's artifacts.
  Hardened like the bootstrap state bucket (versioned, AES256, public-access-blocked),
  plus a lifecycle rule expiring objects after 30 days.
- `codedeploy.tf` — the `policyflow-app` CodeDeploy application and a deployment
  group targeting the host by its `Name = ${project_name}-host` EC2 tag
  (`CodeDeployDefault.AllAtOnce`, in-place, no ASG/ELB). Its service role mirrors
  the inline-policy style with EC2/tag discovery on `*` (read-only lookups that
  cannot be resource-scoped). The actual deploy logic (appspec + hooks) is Epic 11,
  so the group is wired but stays red until then.
- `codepipeline.tf` — the GitHub (CodeStar) connection plus the
  `policyflow-pipeline` three-stage pipeline: Source (GitHub via the connection,
  watching `github_branch`), Build (the existing `policyflow-build` project), Deploy
  (the CodeDeploy group). Its service role's inline policy is ARN-scoped:
  artifact-bucket read/write, `UseConnection` on the connection, `StartBuild` on the
  build project, and the `CreateDeployment`/`Get*`/`RegisterApplicationRevision`
  actions on the app + deployment-group + deployment-config ARNs. The connection is
  created PENDING and must be authorized once (see below).
- `ssm.tf` — two SecureString parameter resources for the stack's secrets
  (`/policyflow/postgres/password`, `/policyflow/rabbitmq/password`). Each holds a
  non-secret `CHANGE_ME` placeholder with `ignore_changes = [value]`; the real
  values are injected out-of-band (see below) and never enter code or state.
- `network.tf` — one security group on the default VPC: 80/443 from the internet,
  22 from `ssh_ingress_cidr`, all egress.
- `ec2.tf` — the `t3.small` AL2023 host with an encrypted root volume, plus an
  Elastic IP and its association for a stable public address.
- `route53.tf` — reads the **existing** hosted zone (`var.hosted_zone_name`) as a
  `data` source (never created — it must already exist and be delegated) and creates
  a plain A record (`var.domain_name`, TTL 300) pointing at the host's Elastic IP.
  An EIP is a literal IPv4, so this is a simple A record, not an ALIAS. No
  security-group change — `network.tf` already opens 80 + 443 to the internet.
- `user-data.sh` — host bootstrap (installs Docker, the Docker Compose v2 CLI
  plugin, and the CodeDeploy agent binary). Idempotent.
- `outputs.tf` — `public_ip` (the EIP), `instance_id`, `security_group_id`,
  `iam_instance_profile_name`, `ssm_parameter_names`, `ecr_repository_urls`,
  `codebuild_project_name`, `github_connection_arn`, `codepipeline_name`,
  `codedeploy_app_name`, `codedeploy_deployment_group_name`,
  `artifact_bucket_name`, and `app_url` (`https://${domain_name}`).
- `terraform.tfvars.example` — template; copy to `terraform.tfvars` (git-ignored)
  and set the operator's real SSH CIDR and the GitHub source repository URL.

## Apply flow (manual author step — needs AWS credentials and incurs real cost)

`terraform plan`/`apply` are **not** run in CI or locally during development; they
stand up billable AWS resources and require credentials. The author runs them by
hand:

1. **Bootstrap the remote state, once:**
   ```sh
   cd infra/bootstrap
   terraform init
   terraform apply
   ```
2. **Initialize the root config against the S3 backend:**
   ```sh
   cd infra
   terraform init
   ```
3. **Apply, providing the required SSH CIDR:**
   ```sh
   cp terraform.tfvars.example terraform.tfvars   # then edit ssh_ingress_cidr
   terraform apply
   ```

The committed `.terraform.lock.hcl` pins provider versions; keep it in version
control.

## Inject the secret values (out-of-band, after apply)

`ssm.tf` creates the SecureString parameters with a `CHANGE_ME` placeholder and
`ignore_changes = [value]`, so the real secrets live only in SSM — never in repo,
code, or Terraform state. Set them by hand once (and whenever they rotate):

```sh
aws ssm put-parameter --type SecureString --overwrite \
  --name /policyflow/postgres/password --value '<real-postgres-password>'

aws ssm put-parameter --type SecureString --overwrite \
  --name /policyflow/rabbitmq/password --value '<real-rabbitmq-password>'
```

`terraform output ssm_parameter_names` lists the paths that need populating.

## Build and push the images (manual proof, after apply)

The `policyflow-build` CodeBuild project builds the core + frontend images and
pushes them to ECR. Because the source is private, import a CodeBuild source
credential **once** (a sanctioned one-time bootstrap, like the GitHub connection
in Epic 9) so the project can clone the repo:

```sh
aws codebuild import-source-credentials --server-type GITHUB \
  --auth-type PERSONAL_ACCESS_TOKEN --token <github-personal-access-token>
```

Then trigger a build and watch both images land in ECR:

```sh
aws codebuild start-build --project-name policyflow-build
```

When it succeeds, both repositories hold the new tags — verify with:

```sh
aws ecr list-images --repository-name policyflow-core
aws ecr list-images --repository-name policyflow-frontend
```

Each should show a `:<short-sha>` tag and a `:latest` tag. This is the build
half of the push→build→deploy path; Epic 9 wires CodePipeline/CodeDeploy around
this same project. Running a build incurs real cost, so it is the author's manual
step — not run in CI or during development.

## Authorize the GitHub connection (one-time)

`codepipeline.tf` creates the GitHub (CodeStar) connection in **PENDING** state —
Terraform cannot complete the OAuth handshake, so this one interactive step in the
AWS console is the sanctioned manual bootstrap (the connection equivalent of the
CodeBuild source credential above). After `apply`:

1. Open the AWS console → **Developer Tools → Settings → Connections**.
2. Select the `policyflow-github` connection (PENDING) and choose **Update pending
   connection**.
3. Authorize the AWS Connector for GitHub against the repository named in
   `github_repository_id`.

`terraform output github_connection_arn` gives the connection to authorize. Once it
is **Available**, a push to `github_branch` (default `main`) auto-triggers the
pipeline (Source → Build → Deploy) with no webhook to configure. The **Deploy stage
stays red** ("appspec not found") until Epic 11 supplies `ops/appspec.yml` + the
lifecycle hooks — Epic 9 delivers the structural end-to-end path, not a green deploy.

## TLS issuance + renewal (Epic 10 — one-time host bootstrap, then automatic)

DNS (`route53.tf`) points `policyflow.joeyshub.com` at the EIP, but the certificate
is issued and renewed by the compose stack on the host, not by Terraform. The base
`docker-compose.yml` stays HTTP-only for local dev; the new root
`docker-compose.prod.yml` overlay adds TLS termination (`frontend/nginx.tls.conf`),
the named `letsencrypt` + `certbot-webroot` volumes, and an in-stack `certbot`
renewal sidecar — **no host cron**.

1. **Point DNS first.** After `apply`, confirm `policyflow.joeyshub.com` resolves to
   the EIP (`terraform output public_ip`). HTTP-01 issuance needs the name reachable.
2. **Set the certbot vars in `.env` on the host** — `CERTBOT_EMAIL`,
   `CERTBOT_DOMAIN=policyflow.joeyshub.com`, `CERTBOT_STAGING` (`1` while testing the
   flow against Let's Encrypt staging, `0` for the real trusted cert).
3. **Run the one-time issuance bootstrap** (a sanctioned manual step, like
   authorizing the GitHub connection):
   ```sh
   ./ops/init-letsencrypt.sh
   ```
   It downloads certbot's recommended TLS options into the `letsencrypt` volume,
   boots nginx on a throwaway dummy cert, requests the real cert over HTTP-01, and
   reloads nginx onto it. See `ops/README.md`.
4. **Bring the full prod stack up** — the `certbot` sidecar then renews every 12h and
   nginx reloads every 6h to pick up renewed certs:
   ```sh
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   ```

`terraform output app_url` gives the resulting HTTPS URL. The live proof
(run the bootstrap → real cert → `https://policyflow.joeyshub.com` valid) is the
deferred manual verification exercised in Epics 11–12 — it is not run during
development.

**Fallback (Risk #2 — HTTP-01 issuance fails):** if Let's Encrypt HTTP-01 cannot
validate the domain (e.g. port 80 blocked upstream, or a CAA/rate-limit problem),
the contingency is to terminate TLS at an AWS-managed cert instead: request an **ACM
certificate** for `policyflow.joeyshub.com` (DNS-validated via the same Route 53
zone) and put an **Application Load Balancer** in front of the host with an HTTPS
listener using that cert, forwarding to the instance on port 80. This trades the
self-renewing in-stack cert for managed ACM renewal at the cost of an ALB. It is
documented as a written contingency only — **no ALB is built in this epic.**

## Local checks (no apply)

```sh
terraform fmt -recursive infra/
cd infra           && terraform init -backend=false && terraform validate
cd infra/bootstrap && terraform init -backend=false && terraform validate
```

## Not here yet

- The Deploy stage is wired but stays red until Epic 11 supplies `ops/appspec.yml`
  + the lifecycle hooks; Source → Build runs green (images land in ECR).
- The deploy hooks (Epic 11) and the hands-off exit test (Epic 12) follow next.
