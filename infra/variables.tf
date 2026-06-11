variable "region" {
  description = "AWS region the network and host are provisioned in."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project tag applied to every resource via the provider default_tags."
  type        = string
  default     = "policyflow"
}

variable "instance_type" {
  description = "EC2 instance class for the always-on host. x86_64 to match the image arch CodeBuild targets later."
  type        = string
  default     = "t3.small"
}

variable "ssh_ingress_cidr" {
  description = "CIDR block allowed to reach SSH (port 22) on the host. REQUIRED and intentionally has no default so an apply can never silently open port 22 to the world. Set this to the operator's own address, e.g. 203.0.113.4/32."
  type        = string
}

variable "source_repository_url" {
  description = "HTTPS clone URL of the GitHub repository CodeBuild builds from, e.g. https://github.com/owner/PolicyFlow.git. REQUIRED with no default. A private repo needs a one-time CodeBuild source credential imported by hand (see infra/README.md)."
  type        = string
}

variable "github_repository_id" {
  description = "FullRepositoryId of the GitHub repository the pipeline's Source action watches, in owner/repo form, e.g. owner/PolicyFlow. REQUIRED with no default — distinct from source_repository_url (the clone URL CodeBuild uses)."
  type        = string
}

variable "github_branch" {
  description = "Branch the pipeline's Source action watches; a push here auto-triggers the pipeline."
  type        = string
  default     = "main"
}

variable "hosted_zone_name" {
  description = "Name of the EXISTING Route 53 hosted zone the app record is created in. Read as a data source, never created by this config — the zone must already exist and be delegated."
  type        = string
  default     = "joeyshub.com"
}

variable "domain_name" {
  description = "Fully-qualified domain the host serves over HTTPS; the Route 53 A record and the nginx/certbot TLS config all use this name."
  type        = string
  default     = "policyflow.joeyshub.com"
}
