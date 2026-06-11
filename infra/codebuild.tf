# The image-build project: a CodeBuild project that runs ops/buildspec.yml to
# build the core + frontend images and push them to the ECR repositories
# (ecr.tf). Runnable now via `aws codebuild start-build`; Epic 9's pipeline
# reuses this same project, overriding source to the pipeline artifact at runtime.
#
# IAM mirrors iam.tf: an assume-role trust document plus inline least-privilege
# policies scoped by ARN prefix.

# Trust policy: only the CodeBuild service may assume this role.
data "aws_iam_policy_document" "build_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "build" {
  name               = "${var.project_name}-build"
  assume_role_policy = data.aws_iam_policy_document.build_assume_role.json

  tags = {
    Name = "${var.project_name}-build"
  }
}

# --- ECR push ---------------------------------------------------------------
# The build pushes the freshly built images to ECR. GetAuthorizationToken
# cannot be resource-scoped, so it is granted on "*"; the layer/image push and
# pull actions are scoped to this project's repositories by ARN prefix.
data "aws_iam_policy_document" "build_ecr_push" {
  statement {
    sid       = "EcrAuthorizationToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPushProjectImages"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
    ]
    resources = [
      "arn:aws:ecr:${var.region}:${data.aws_caller_identity.current.account_id}:repository/${var.project_name}-*",
    ]
  }
}

resource "aws_iam_role_policy" "build_ecr_push" {
  name   = "${var.project_name}-build-ecr-push"
  role   = aws_iam_role.build.id
  policy = data.aws_iam_policy_document.build_ecr_push.json
}

# --- CloudWatch Logs --------------------------------------------------------
# The build writes its console output to its own CloudWatch log group, scoped
# to that group's ARN (the log group is created by the project below).
data "aws_iam_policy_document" "build_logs" {
  statement {
    sid    = "WriteBuildLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/codebuild/${var.project_name}-build",
      "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/codebuild/${var.project_name}-build:*",
    ]
  }
}

resource "aws_iam_role_policy" "build_logs" {
  name   = "${var.project_name}-build-logs"
  role   = aws_iam_role.build.id
  policy = data.aws_iam_policy_document.build_logs.json
}

# --- Pipeline artifact bucket -----------------------------------------------
# In pipeline mode (Epic 9) CodeBuild runs as the pipeline's Build action and
# downloads the Source input artifact from the artifact bucket (artifacts.tf).
# GetBucketLocation is on the bucket itself; the object read/write is scoped to
# the bucket's objects.
data "aws_iam_policy_document" "build_artifacts" {
  statement {
    sid       = "S3GetBucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.pipeline_artifacts.arn]
  }

  statement {
    sid    = "S3ReadWriteArtifacts"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.pipeline_artifacts.arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "build_artifacts" {
  name   = "${var.project_name}-build-artifacts"
  role   = aws_iam_role.build.id
  policy = data.aws_iam_policy_document.build_artifacts.json
}

resource "aws_codebuild_project" "build" {
  name         = "${var.project_name}-build"
  description  = "Builds the ${var.project_name} core + frontend images and pushes them to ECR."
  service_role = aws_iam_role.build.arn

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/amazonlinux2-x86_64-standard:5.0"
    type            = "LINUX_CONTAINER"
    privileged_mode = true # Required to run docker build inside the build container.

    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = var.region
    }

    environment_variable {
      name  = "CORE_REPOSITORY_URL"
      value = aws_ecr_repository.images["${var.project_name}-core"].repository_url
    }

    environment_variable {
      name  = "FRONTEND_REPOSITORY_URL"
      value = aws_ecr_repository.images["${var.project_name}-frontend"].repository_url
    }
  }

  source {
    type            = "GITHUB"
    location        = var.source_repository_url
    buildspec       = "ops/buildspec.yml"
    git_clone_depth = 1
  }

  logs_config {
    cloudwatch_logs {
      group_name = "/aws/codebuild/${var.project_name}-build"
    }
  }

  tags = {
    Name = "${var.project_name}-build"
  }
}
