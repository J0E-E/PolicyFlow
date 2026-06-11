# The pipeline artifact store: a private S3 bucket CodePipeline uses to pass
# artifacts between stages (the Source checkout the Build and Deploy stages read).
# The account id is folded into the bucket name for global uniqueness. Hardened
# the same way as the bootstrap state bucket — versioned, AES256-encrypted, and
# fully private — plus a 30-day object-expiration lifecycle rule for housekeeping.

resource "aws_s3_bucket" "pipeline_artifacts" {
  bucket = "${var.project_name}-pipeline-artifacts-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "${var.project_name}-pipeline-artifacts"
  }
}

resource "aws_s3_bucket_versioning" "pipeline_artifacts" {
  bucket = aws_s3_bucket.pipeline_artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "pipeline_artifacts" {
  bucket = aws_s3_bucket.pipeline_artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "pipeline_artifacts" {
  bucket = aws_s3_bucket.pipeline_artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Expire pipeline artifacts after 30 days so old Source checkouts do not
# accumulate — same housekeeping spirit as the ECR untagged-14-day rule.
resource "aws_s3_bucket_lifecycle_configuration" "pipeline_artifacts" {
  bucket = aws_s3_bucket.pipeline_artifacts.id

  rule {
    id     = "expire-artifacts-after-30-days"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }
  }
}
