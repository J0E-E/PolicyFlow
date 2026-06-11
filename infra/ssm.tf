# The "SSM secrets seam": SecureString parameter resources for the stack's
# secrets. Terraform owns the resources but NOT their values — each is created
# with a non-secret placeholder and ignore_changes on value, so the real secret
# is injected out-of-band (`aws ssm put-parameter --overwrite`, see README) and
# never read into or overwritten by Terraform state.

locals {
  # path => human-readable Name tag. Extend this map to add more secrets.
  host_secret_parameters = {
    "/${var.project_name}/postgres/password" = "${var.project_name}-postgres-password"
    "/${var.project_name}/rabbitmq/password" = "${var.project_name}-rabbitmq-password"
  }
}

resource "aws_ssm_parameter" "host_secret" {
  for_each = local.host_secret_parameters

  name  = each.key
  type  = "SecureString"
  value = "CHANGE_ME"

  tags = {
    Name = each.value
  }

  # The real value is set out-of-band and must never be clobbered by an apply.
  lifecycle {
    ignore_changes = [value]
  }
}
