# The host's IAM identity: a role the EC2 service can assume, wrapped in an
# instance profile and attached to aws_instance.host (see ec2.tf). Permissions
# are granted by the least-privilege inline policies below — ECR pull and SSM
# read only. CodeDeploy's S3 artifact read is deferred to Epic 9.

# Trust policy: only the EC2 service may assume this role.
data "aws_iam_policy_document" "host_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "host" {
  name               = "${var.project_name}-host"
  assume_role_policy = data.aws_iam_policy_document.host_assume_role.json

  tags = {
    Name = "${var.project_name}-host"
  }
}

resource "aws_iam_instance_profile" "host" {
  name = "${var.project_name}-host"
  role = aws_iam_role.host.name

  tags = {
    Name = "${var.project_name}-host"
  }
}

# --- ECR pull ---------------------------------------------------------------
# The host pulls the stack's images from ECR. GetAuthorizationToken cannot be
# resource-scoped, so it is granted on "*"; the layer/image reads are scoped to
# this project's repositories by ARN prefix.
data "aws_iam_policy_document" "host_ecr_pull" {
  statement {
    sid       = "EcrAuthorizationToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPullProjectImages"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    resources = [
      "arn:aws:ecr:${var.region}:${data.aws_caller_identity.current.account_id}:repository/${var.project_name}-*",
    ]
  }
}

resource "aws_iam_role_policy" "host_ecr_pull" {
  name   = "${var.project_name}-host-ecr-pull"
  role   = aws_iam_role.host.id
  policy = data.aws_iam_policy_document.host_ecr_pull.json
}

# --- SSM read ---------------------------------------------------------------
# The host reads its SecureString secrets from this project's SSM namespace.
# kms:Decrypt is granted on "*" but gated by a ViaService condition so the key
# can only be used through SSM (covering the AWS-managed aws/ssm key without
# naming a key ARN), and nothing else.
data "aws_iam_policy_document" "host_ssm_read" {
  statement {
    sid    = "SsmReadProjectParameters"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]
    resources = [
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/*",
    ]
  }

  statement {
    sid       = "KmsDecryptViaSsmOnly"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "host_ssm_read" {
  name   = "${var.project_name}-host-ssm-read"
  role   = aws_iam_role.host.id
  policy = data.aws_iam_policy_document.host_ssm_read.json
}
