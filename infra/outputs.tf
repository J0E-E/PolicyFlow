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
