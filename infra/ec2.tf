# The always-on host: AL2023 on t3.small, in a default-VPC subnet, behind the
# host security group, bootstrapped with Docker + the CodeDeploy agent.
resource "aws_instance" "host" {
  ami                    = data.aws_ssm_parameter.amazon_linux_2023.value
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.host.id]
  iam_instance_profile   = aws_iam_instance_profile.host.name

  user_data = templatefile("${path.module}/user-data.sh", {
    region = var.region
  })

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  tags = {
    Name = "${var.project_name}-host"
  }
}

# Stable public address so DNS (Epic 10) can point at something that survives
# instance replacement.
resource "aws_eip" "host" {
  domain = "vpc"

  tags = {
    Name = "${var.project_name}-host"
  }
}

resource "aws_eip_association" "host" {
  instance_id   = aws_instance.host.id
  allocation_id = aws_eip.host.id
}
