# infra

Terraform for all AWS resources (network, EC2 host, IAM, ECR, CodeBuild,
CodePipeline, CodeDeploy, Route 53, TLS). Filled in across Epics 6–11.

## What is here today (Epics 6–8 — network, host, IAM, SSM, ECR, CodeBuild)

- `bootstrap/` — a small standalone config (with **local** state) that creates the
  S3 bucket + DynamoDB table this root config uses for remote state. See
  `bootstrap/README.md`.
- `versions.tf` — Terraform + AWS provider (`~> 5`) requirements and the `backend "s3"`
  block pointing at the bootstrap bucket/table.
- `providers.tf` — the AWS provider, region from `var.region`, `default_tags` of
  `Project = policyflow` on every resource.
- `variables.tf` — `region`, `project_name`, `instance_type`, and the **required**
  `ssh_ingress_cidr` and `source_repository_url` (the GitHub clone URL CodeBuild
  builds from).
- `data.tf` — reads the default VPC + its subnets (never created), the latest
  AL2023 x86_64 AMI from the public SSM parameter, and the current account id
  (used to build the IAM policy ARNs).
- `iam.tf` — the host's IAM role + instance profile (attached in `ec2.tf`), with
  two least-privilege inline policies: ECR pull (token on `*`, layer/image reads
  scoped to `${project_name}-*` repositories) and SSM read (parameters under
  `/${project_name}/*`, plus `kms:Decrypt` gated to SSM-only via a `kms:ViaService`
  condition). CodeDeploy's S3 artifact read is deferred to Epic 9.
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
  project's `/aws/codebuild/${project_name}-build` group. The repo URLs + region
  are passed to the buildspec as `environment_variable`s.
- `ssm.tf` — two SecureString parameter resources for the stack's secrets
  (`/policyflow/postgres/password`, `/policyflow/rabbitmq/password`). Each holds a
  non-secret `CHANGE_ME` placeholder with `ignore_changes = [value]`; the real
  values are injected out-of-band (see below) and never enter code or state.
- `network.tf` — one security group on the default VPC: 80/443 from the internet,
  22 from `ssh_ingress_cidr`, all egress.
- `ec2.tf` — the `t3.small` AL2023 host with an encrypted root volume, plus an
  Elastic IP and its association for a stable public address.
- `user-data.sh` — host bootstrap (installs Docker, the Docker Compose v2 CLI
  plugin, and the CodeDeploy agent binary). Idempotent.
- `outputs.tf` — `public_ip` (the EIP), `instance_id`, `security_group_id`,
  `iam_instance_profile_name`, `ssm_parameter_names`, `ecr_repository_urls`, and
  `codebuild_project_name`.
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

## Local checks (no apply)

```sh
terraform fmt -recursive infra/
cd infra           && terraform init -backend=false && terraform validate
cd infra/bootstrap && terraform init -backend=false && terraform validate
```

## Not here yet

- The CodeDeploy agent binary is installed and the host now has its instance
  profile (Epic 7), but the agent stays idle until Epic 9 adds a deployment group.
  CodeDeploy's S3 artifact read permission is granted alongside it in Epic 9.
- CodePipeline/CodeDeploy wiring (Epic 9), Route 53 + TLS (Epic 10), and the
  deploy hooks (Epic 11) follow in later epics.
