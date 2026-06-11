terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5"
    }
  }

  # Remote state lives in the bucket + lock table created by infra/bootstrap.
  # Run bootstrap once before `terraform init` here.
  backend "s3" {
    bucket         = "policyflow-terraform-state"
    key            = "walking-skeleton/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "policyflow-terraform-lock"
    encrypt        = true
  }
}
