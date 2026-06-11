#!/bin/sh
# CodeDeploy AfterInstall hook. Runs after the agent has copied the bundle to
# APP_DIR. Prepares everything the stack needs before it starts:
#   1. Write APP_DIR/.env from the committed non-secret defaults + the two SSM
#      passwords + the two ECR image refs (exercising Epic 7's "stack reads SSM
#      at boot" seam — secrets never live in the repo).
#   2. Log Docker in to ECR.
#   3. Pull the freshly-built images so ApplicationStart never builds on the host.
set -eu

# shellcheck source=ops/deploy/lib.sh
. "$(dirname "$0")/lib.sh"

cd "$APP_DIR"

echo "### Fetching the secret passwords from SSM ..."
POSTGRES_PASSWORD="$(aws ssm get-parameter --with-decryption \
  --name /policyflow/postgres/password --query Parameter.Value --output text \
  --region "$REGION")"
RABBITMQ_DEFAULT_PASS="$(aws ssm get-parameter --with-decryption \
  --name /policyflow/rabbitmq/password --query Parameter.Value --output text \
  --region "$REGION")"

echo "### Writing $APP_DIR/.env (non-secret defaults + SSM secrets + image refs) ..."
# Start from the committed non-secret defaults, then append the secrets and the
# image refs. The file is recreated every deploy so it never drifts.
cp ops/deploy/prod.env.defaults .env
{
  echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD"
  echo "RABBITMQ_DEFAULT_PASS=$RABBITMQ_DEFAULT_PASS"
  echo "CORE_IMAGE=$CORE_IMAGE"
  echo "FRONTEND_IMAGE=$FRONTEND_IMAGE"
} >> .env
chmod 600 .env

echo "### Logging Docker in to ECR ($REGISTRY) ..."
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

echo "### Pulling the freshly-built images ..."
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES pull

echo "### AfterInstall complete."
