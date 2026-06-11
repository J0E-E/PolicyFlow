#!/bin/sh
# CodeDeploy ApplicationStart hook. Brings the stack up with the images pulled in
# AfterInstall. This is also the migrate + seed step: core's entrypoint runs
# `alembic upgrade head` then `python -m app.seed` before serving (Epic 3), so a
# failed migration makes core exit and ValidateService then fails the deploy.
set -eu

# shellcheck source=ops/deploy/lib.sh
. "$(dirname "$0")/lib.sh"

cd "$APP_DIR"

echo "### Starting the stack (migrate + seed run inside core's entrypoint) ..."
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES up -d

echo "### ApplicationStart complete."
