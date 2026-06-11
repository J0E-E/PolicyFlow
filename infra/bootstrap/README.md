# infra/bootstrap

One-time bootstrap that solves the chicken-and-egg problem of remote state: the
root config in `../` keeps its state in S3 with a DynamoDB lock, but those two
resources have to exist *before* that backend can initialize. This config creates
them, and uses **local** state itself (so it has no such dependency).

## What it creates

- An S3 bucket for the root config's Terraform state — versioned, encrypted
  (AES256), and with all public access blocked.
- A DynamoDB table for state locking.

## How to run (one time, by hand, with AWS credentials)

```sh
cd infra/bootstrap
terraform init
terraform apply
```

The bucket and lock-table names are emitted as outputs and must match the
`backend "s3"` block in `../versions.tf` (they share the same defaults:
`policyflow-terraform-state` and `policyflow-terraform-lock`).

After this succeeds once, initialize the root config (`cd ../ && terraform init`)
and it will store its state in the bucket created here. You should not need to run
bootstrap again.
