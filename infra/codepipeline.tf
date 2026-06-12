# The CI/CD trigger: a CodeStar GitHub connection plus a three-stage pipeline
# (Source -> Build -> Deploy). A push to var.github_branch auto-triggers the
# pipeline, which reuses the existing CodeBuild project (codebuild.tf) for Build
# and the CodeDeploy app + deployment group (codedeploy.tf) for Deploy.
#
# IAM mirrors iam.tf/codebuild.tf: an assume-role trust document plus an inline
# least-privilege policy scoped by ARN.

# The GitHub connection. Terraform creates it in PENDING state; the one-time
# interactive authorization in the AWS console is the sanctioned manual bootstrap
# (see infra/README.md). Once authorized it is reusable across pipelines.
resource "aws_codestarconnections_connection" "github" {
  name          = "${var.project_name}-github"
  provider_type = "GitHub"

  tags = {
    Name = "${var.project_name}-github"
  }
}

# Trust policy: only the CodePipeline service may assume this role.
data "aws_iam_policy_document" "pipeline_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codepipeline.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = "${var.project_name}-pipeline"
  assume_role_policy = data.aws_iam_policy_document.pipeline_assume_role.json

  tags = {
    Name = "${var.project_name}-pipeline"
  }
}

# The pipeline's least-privilege permissions: read/write the artifact bucket,
# use the GitHub connection for the Source action, start the build, and create
# the deployment. Each statement is scoped to the exact ARN it acts on.
data "aws_iam_policy_document" "pipeline" {
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

  statement {
    sid       = "UseGitHubConnection"
    effect    = "Allow"
    actions   = ["codestar-connections:UseConnection"]
    resources = [aws_codestarconnections_connection.github.arn]
  }

  statement {
    sid    = "StartBuild"
    effect = "Allow"
    actions = [
      "codebuild:StartBuild",
      "codebuild:BatchGetBuilds",
    ]
    resources = [aws_codebuild_project.build.arn]
  }

  statement {
    sid    = "CreateDeployment"
    effect = "Allow"
    actions = [
      "codedeploy:CreateDeployment",
      "codedeploy:GetApplication",
      "codedeploy:GetApplicationRevision",
      "codedeploy:GetDeployment",
      "codedeploy:GetDeploymentConfig",
      "codedeploy:RegisterApplicationRevision",
    ]
    resources = [
      aws_codedeploy_app.app.arn,
      "arn:aws:codedeploy:${var.region}:${data.aws_caller_identity.current.account_id}:deploymentgroup:${aws_codedeploy_app.app.name}/${aws_codedeploy_deployment_group.host.deployment_group_name}",
      "arn:aws:codedeploy:${var.region}:${data.aws_caller_identity.current.account_id}:deploymentconfig:CodeDeployDefault.AllAtOnce",
    ]
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "${var.project_name}-pipeline"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline.json
}

# The pipeline itself: Source (GitHub via the connection) -> Build (the existing
# CodeBuild project) -> Deploy (the CodeDeploy group). The v2 connection
# auto-triggers on a push to github_branch — no separate webhook resource.
resource "aws_codepipeline" "pipeline" {
  name     = "${var.project_name}-pipeline"
  role_arn = aws_iam_role.pipeline.arn

  artifact_store {
    type     = "S3"
    location = aws_s3_bucket.pipeline_artifacts.bucket
  }

  stage {
    name = "Source"

    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["source_output"]

      configuration = {
        ConnectionArn    = aws_codestarconnections_connection.github.arn
        FullRepositoryId = var.github_repository_id
        BranchName       = var.github_branch
      }
    }
  }

  stage {
    name = "Build"

    # No output artifact: the build's product is the images pushed to ECR, not
    # a pipeline artifact.
    action {
      name            = "Build"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["source_output"]

      configuration = {
        ProjectName = aws_codebuild_project.build.name
      }
    }
  }

  stage {
    name = "Deploy"

    # Input is the Source checkout (source_output), which carries appspec.yml
    # (at the repo root, where CodeDeploy requires it) + the lifecycle hooks in
    # ops/deploy/. Landed in Epic 11, so this stage is wired and active: the
    # hooks run on deploy.
    action {
      name            = "Deploy"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "CodeDeploy"
      version         = "1"
      input_artifacts = ["source_output"]

      configuration = {
        ApplicationName     = aws_codedeploy_app.app.name
        DeploymentGroupName = aws_codedeploy_deployment_group.host.deployment_group_name
      }
    }
  }

  tags = {
    Name = "${var.project_name}-pipeline"
  }
}
