# The default VPC and its subnets are read as data sources, never created.
data "aws_vpc" "default" {
  default = true
}

# AZs in this region that actually offer the chosen instance type. Not every AZ
# offers every type — e.g. us-east-1e has no t3.small — and selecting a subnet in
# an unsupported AZ fails RunInstances. We read the offered AZs and constrain the
# subnet query to them so the host always lands somewhere it can run.
data "aws_ec2_instance_type_offerings" "host" {
  location_type = "availability-zone"

  filter {
    name   = "instance-type"
    values = [var.instance_type]
  }
}

# Default-VPC subnets restricted to an AZ that offers the instance type, so
# ids[0] can never pick an AZ where the host type is unavailable.
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "availability-zone"
    values = data.aws_ec2_instance_type_offerings.host.locations
  }
}

# Latest Amazon Linux 2023 x86_64 AMI, resolved from the public SSM parameter
# AWS keeps current — no hard-coded AMI id that would drift over time.
data "aws_ssm_parameter" "amazon_linux_2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# The current account id, used to build the IAM policy resource ARNs in iam.tf.
data "aws_caller_identity" "current" {}
