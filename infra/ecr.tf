# The image registry: one ECR repository per image in the stack (core +
# frontend), matching the one-repo-per-image decision from Epic 1. CodeBuild
# (codebuild.tf) builds and pushes here; the host (iam.tf) pulls from here.
#
# Repos are MUTABLE because every build pushes both an immutable :<short-sha>
# tag (the deploy/rollback target) and a moving :latest tag (convenience).

locals {
  # One repository per image. Names match the ${project_name}-* ARN prefix the
  # host's ECR-pull policy (iam.tf) and CodeBuild's push policy are scoped to.
  ecr_repositories = toset([
    "${var.project_name}-core",
    "${var.project_name}-frontend",
  ])
}

resource "aws_ecr_repository" "images" {
  for_each = local.ecr_repositories

  name = each.value

  # MUTABLE so the moving :latest tag can be re-pointed on every push.
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = each.value
  }
}

# Expire untagged images after 14 days so layers orphaned by re-pushed :latest
# tags do not accumulate. Tagged images (every :<short-sha> and the current
# :latest) are kept — only the dangling untagged ones are cleaned up.
resource "aws_ecr_lifecycle_policy" "images" {
  for_each = aws_ecr_repository.images

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 14 days."
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 14
        }
        action = {
          type = "expire"
        }
      },
    ]
  })
}
