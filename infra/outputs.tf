output "public_ip" {
  description = "Stable public IP of the host (the Elastic IP). DNS points here in Epic 10."
  value       = aws_eip.host.public_ip
}

output "instance_id" {
  description = "EC2 instance id of the host."
  value       = aws_instance.host.id
}

output "security_group_id" {
  description = "Id of the host security group."
  value       = aws_security_group.host.id
}

output "iam_instance_profile_name" {
  description = "Name of the IAM instance profile attached to the host."
  value       = aws_iam_instance_profile.host.name
}

output "ssm_parameter_names" {
  description = "SSM SecureString parameter paths whose values the operator must populate out-of-band."
  value       = keys(local.host_secret_parameters)
}

output "ecr_repository_urls" {
  description = "Map of ECR repository name to its push/pull URL (core + frontend)."
  value       = { for name, repository in aws_ecr_repository.images : name => repository.repository_url }
}

output "codebuild_project_name" {
  description = "Name of the CodeBuild project that builds and pushes the images; pass to `aws codebuild start-build --project-name`."
  value       = aws_codebuild_project.build.name
}

output "github_connection_arn" {
  description = "ARN of the GitHub (CodeStar) connection. Created PENDING — authorize it once in the AWS console before the pipeline can run (see infra/README.md)."
  value       = aws_codestarconnections_connection.github.arn
}

output "codepipeline_name" {
  description = "Name of the CodePipeline that runs Source -> Build -> Deploy."
  value       = aws_codepipeline.pipeline.name
}

output "codedeploy_app_name" {
  description = "Name of the CodeDeploy application."
  value       = aws_codedeploy_app.app.name
}

output "codedeploy_deployment_group_name" {
  description = "Name of the CodeDeploy deployment group targeting the host."
  value       = aws_codedeploy_deployment_group.host.deployment_group_name
}

output "artifact_bucket_name" {
  description = "Name of the S3 bucket holding CodePipeline artifacts."
  value       = aws_s3_bucket.pipeline_artifacts.bucket
}
