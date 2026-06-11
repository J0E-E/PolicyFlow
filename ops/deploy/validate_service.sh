#!/bin/sh
# CodeDeploy ValidateService hook. Polls the core container's health for up to
# ~2 minutes and exits non-zero if it never becomes healthy, so a bad migrate or
# a failed boot turns into a failed deployment instead of a silently broken host.
set -eu

# shellcheck source=ops/deploy/lib.sh
. "$(dirname "$0")/lib.sh"

cd "$APP_DIR"

ATTEMPT_LIMIT=24       # 24 attempts x 5s = ~2 minutes
SECONDS_BETWEEN=5

echo "### Waiting for core to report healthy (up to ~2 minutes) ..."
attempt=1
while [ "$attempt" -le "$ATTEMPT_LIMIT" ]; do
  # Ask the core container itself for its health endpoint — core publishes no
  # host port (prod parity), so probe from inside the container.
  # shellcheck disable=SC2086
  if docker compose $COMPOSE_FILES exec -T core \
      curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then
    echo "### core is healthy after $attempt attempt(s)."
    exit 0
  fi
  echo "    attempt $attempt/$ATTEMPT_LIMIT: core not healthy yet, retrying in ${SECONDS_BETWEEN}s ..."
  attempt=$((attempt + 1))
  sleep "$SECONDS_BETWEEN"
done

echo "### core never became healthy within the timeout — failing the deployment." >&2
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES ps >&2 || true
exit 1
