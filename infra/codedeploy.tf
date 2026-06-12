# The deploy target: a CodeDeploy application + deployment group pointed at the
# EC2 host by its Name tag (set in ec2.tf). The pipeline's Deploy stage
# (codepipeline.tf) hands this group the Source checkout; the actual deploy
# logic (appspec.yml at the repo root + lifecycle hooks) landed in Epic 11, so
# the group is wired and active: the hooks run on deploy.
#
# IAM mirrors iam.tf/codebuild.tf: an assume-role trust document plus an inline
# least-privilege policy.

resource "aws_codedeploy_app" "app" {
  name             = "${var.project_name}-app"
  compute_platform = "Server"

  tags = {
    Name = "${var.project_name}-app"
  }
}

# Trust policy: only the CodeDeploy service may assume this role.
data "aws_iam_policy_document" "deploy_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codedeploy.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${var.project_name}-deploy"
  assume_role_policy = data.aws_iam_policy_document.deploy_assume_role.json

  tags = {
    Name = "${var.project_name}-deploy"
  }
}

# --- EC2 + tag discovery ----------------------------------------------------
# CodeDeploy finds the target host by reading EC2 instance details and resource
# tags. Neither describe/discovery call can be resource-scoped, so both are
# granted on "*" — they are read-only lookups, not mutations.
data "aws_iam_policy_document" "deploy_ec2_discovery" {
  statement {
    sid    = "DescribeAndDiscoverInstances"
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "tag:GetResources",
      "tag:GetTags",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deploy_ec2_discovery" {
  name   = "${var.project_name}-deploy-ec2-discovery"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy_ec2_discovery.json
}

# In-place deployment to the host, found by its Name tag (set in ec2.tf). No
# Auto Scaling group and no load balancer — a single always-on instance.
resource "aws_codedeploy_deployment_group" "host" {
  app_name               = aws_codedeploy_app.app.name
  deployment_group_name  = "${var.project_name}-host"
  service_role_arn       = aws_iam_role.deploy.arn
  deployment_config_name = "CodeDeployDefault.AllAtOnce"

  deployment_style {
    deployment_option = "WITHOUT_TRAFFIC_CONTROL"
    deployment_type   = "IN_PLACE"
  }

  ec2_tag_filter {
    key   = "Name"
    type  = "KEY_AND_VALUE"
    value = "${var.project_name}-host"
  }
}
