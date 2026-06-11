# infra

Terraform for all AWS resources (network, EC2 host, IAM, ECR, CodeBuild,
CodePipeline, CodeDeploy, Route 53, TLS). Filled in across Epics 6–11.

## What is here today (Epic 6 — network + host)

- `bootstrap/` — a small standalone config (with **local** state) that creates the
  S3 bucket + DynamoDB table this root config uses for remote state. See
  `bootstrap/README.md`.
- `versions.tf` — Terraform + AWS provider (`~> 5`) requirements and the `backend "s3"`
  block pointing at the bootstrap bucket/table.
- `providers.tf` — the AWS provider, region from `var.region`, `default_tags` of
  `Project = policyflow` on every resource.
- `variables.tf` — `region`, `project_name`, `instance_type`, and the **required**
  `ssh_ingress_cidr`.
- `data.tf` — reads the default VPC + its subnets (never created) and the latest
  AL2023 x86_64 AMI from the public SSM parameter.
- `network.tf` — one security group on the default VPC: 80/443 from the internet,
  22 from `ssh_ingress_cidr`, all egress.
- `ec2.tf` — the `t3.small` AL2023 host with an encrypted root volume, plus an
  Elastic IP and its association for a stable public address.
- `user-data.sh` — host bootstrap (installs Docker, the Docker Compose v2 CLI
  plugin, and the CodeDeploy agent binary). Idempotent.
- `outputs.tf` — `public_ip` (the EIP), `instance_id`, `security_group_id`.
- `terraform.tfvars.example` — template; copy to `terraform.tfvars` (git-ignored)
  and set the operator's real SSH CIDR.

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

## Local checks (no apply)

```sh
terraform fmt -recursive infra/
cd infra           && terraform init -backend=false && terraform validate
cd infra/bootstrap && terraform init -backend=false && terraform validate
```

## Not here yet

- **IAM instance profile + SSM parameters land in Epic 7.** The host ships with
  **no** instance profile. The CodeDeploy agent binary is installed but stays idle
  until Epic 7/9 give it a role and a deployment group.
- ECR/CodeBuild (Epic 8), CodePipeline/CodeDeploy wiring (Epic 9), Route 53 + TLS
  (Epic 10), and the deploy hooks (Epic 11) follow in later epics.
