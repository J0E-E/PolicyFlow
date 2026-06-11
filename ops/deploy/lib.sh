#!/bin/sh
# Shared seam for the CodeDeploy lifecycle hooks. Sourced (not executed) by each
# hook so they agree on where the app lives, which AWS account/region they run
# in, the ECR registry to log in to and pull from, and the compose invocation.
#
# Run on the host by the CodeDeploy agent, which has the Epic 7 instance profile
# (ECR pull + SSM read). set -eu is set by each hook before sourcing this.

# Where the appspec installs the bundle (see appspec.yml destination).
APP_DIR=/opt/policyflow

# The base + prod overlay, applied together for every compose call on the host.
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.prod.yml"

# Region from the Instance Metadata Service (IMDSv2: get a token, then read the
# placement region). Account id from STS so nothing is hard-coded per-environment.
IMDS_TOKEN="$(curl -fsS -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 300")"
REGION="$(curl -fsS \
  -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" \
  "http://169.254.169.254/latest/meta-data/placement/region")"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

# The ECR registry the build pushed to, and the two image refs (always :latest —
# Build re-points latest at this commit; see the stakeholder decision in the plan).
REGISTRY="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
CORE_IMAGE="$REGISTRY/policyflow-core:latest"
FRONTEND_IMAGE="$REGISTRY/policyflow-frontend:latest"
