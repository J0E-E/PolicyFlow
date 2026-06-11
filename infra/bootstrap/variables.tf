variable "region" {
  description = "AWS region the remote-state bucket and lock table live in."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project tag applied to every bootstrap resource."
  type        = string
  default     = "policyflow"
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket name that will hold the root config's remote state."
  type        = string
  default     = "policyflow-terraform-state"
}

variable "lock_table_name" {
  description = "DynamoDB table name used for Terraform state locking."
  type        = string
  default     = "policyflow-terraform-lock"
}
