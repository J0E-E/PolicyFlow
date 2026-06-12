#!/bin/sh
# CodeDeploy ValidateService hook. Fails the deployment unless BOTH the API and
# the public edge are actually up:
#   1. core reports healthy (catches a bad migrate or a failed boot), and
#   2. the frontend serves over HTTPS on the host (catches a dead/crash-looping
#      nginx — otherwise a deploy could go green while the site is down).
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
    break
  fi
  if [ "$attempt" -eq "$ATTEMPT_LIMIT" ]; then
    echo "### core never became healthy within the timeout — failing the deployment." >&2
    # shellcheck disable=SC2086
    docker compose $COMPOSE_FILES ps >&2 || true
    exit 1
  fi
  echo "    attempt $attempt/$ATTEMPT_LIMIT: core not healthy yet, retrying in ${SECONDS_BETWEEN}s ..."
  attempt=$((attempt + 1))
  sleep "$SECONDS_BETWEEN"
done

echo "### Verifying the public edge serves over HTTPS on the host ..."
# -k: the cert is valid for the public domain, not 127.0.0.1. We only need proof
# that nginx is up and terminating TLS, not that the name matches.
attempt=1
while [ "$attempt" -le "$ATTEMPT_LIMIT" ]; do
  if curl -fsS -k https://127.0.0.1/ >/dev/null 2>&1; then
    echo "### frontend edge is serving HTTPS after $attempt attempt(s)."
    exit 0
  fi
  echo "    attempt $attempt/$ATTEMPT_LIMIT: edge not serving yet, retrying in ${SECONDS_BETWEEN}s ..."
  attempt=$((attempt + 1))
  sleep "$SECONDS_BETWEEN"
done

echo "### The frontend edge never served within the timeout — failing the deployment." >&2
echo "    On a brand-new host this is expected until the one-time TLS cert is issued" >&2
echo "    via ops/init-letsencrypt.sh (see ops/exit-test-runbook.md); re-deploy after." >&2
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES ps >&2 || true
exit 1
