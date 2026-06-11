output "state_bucket_name" {
  description = "Name of the S3 bucket holding the root config's remote state. Wire this into ../versions.tf backend block."
  value       = aws_s3_bucket.terraform_state.id
}

output "lock_table_name" {
  description = "Name of the DynamoDB table used for state locking. Wire this into ../versions.tf backend block."
  value       = aws_dynamodb_table.terraform_lock.name
}
