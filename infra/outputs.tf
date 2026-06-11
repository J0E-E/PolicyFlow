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
