#!/bin/sh
# CodeDeploy ApplicationStart hook. Brings the stack up with the images pulled in
# AfterInstall. This is also the migrate + seed step: core's entrypoint runs
# `alembic upgrade head` then `python -m app.seed` before serving (Epic 3), so a
# failed migration makes core exit and ValidateService then fails the deploy.
#
# It also self-bootstraps the TLS certificate: on a brand-new host with no cert,
# it lays down a throwaway dummy so nginx can boot, brings the stack up, then
# requests the real Let's Encrypt cert over HTTP-01 and reloads nginx onto it.
# Once a real (certbot-managed) cert exists this is a no-op, so every later deploy
# just does `up -d`. This makes a fresh deploy hands-off — no host-side
# init-letsencrypt.sh run needed (that script stays as a manual fallback).
set -eu

# shellcheck source=ops/deploy/lib.sh
. "$(dirname "$0")/lib.sh"

cd "$APP_DIR"

# CERTBOT_* come from the deploy-written .env (prod.env.defaults). Read them the
# same grep|cut way as init-letsencrypt.sh — the pipe exits 0 so `set -e` is safe.
CERTBOT_DOMAIN="$(grep -E '^CERTBOT_DOMAIN=' .env | cut -d= -f2-)"
CERTBOT_EMAIL="$(grep -E '^CERTBOT_EMAIL=' .env | cut -d= -f2-)"
CERTBOT_STAGING="$(grep -E '^CERTBOT_STAGING=' .env | cut -d= -f2-)"

if [ -z "$CERTBOT_DOMAIN" ] || [ -z "$CERTBOT_EMAIL" ]; then
  echo "### CERTBOT_DOMAIN/EMAIL missing from .env — cannot bootstrap TLS." >&2
  exit 1
fi

LIVE_PATH="/etc/letsencrypt/live/$CERTBOT_DOMAIN"
RENEWAL_CONF="/etc/letsencrypt/renewal/$CERTBOT_DOMAIN.conf"

# A real certbot-managed cert writes the renewal conf; a dummy/absent cert does
# not. Use that to decide whether issuance is needed (idempotent across deploys).
needs_issuance=1
# shellcheck disable=SC2086
if docker compose $COMPOSE_FILES run --rm --entrypoint sh certbot \
    -c "[ -f '$RENEWAL_CONF' ]" >/dev/null 2>&1; then
  needs_issuance=0
fi

if [ "$needs_issuance" = 1 ]; then
  echo "### No TLS certificate yet — laying down a temporary dummy so nginx can boot ..."
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES run --rm --entrypoint sh certbot -c "
    rm -rf '$LIVE_PATH' &&
    mkdir -p '$LIVE_PATH' &&
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
      -keyout '$LIVE_PATH/privkey.pem' \
      -out '$LIVE_PATH/fullchain.pem' \
      -subj '/CN=localhost'"
fi

echo "### Starting the stack (migrate + seed run inside core's entrypoint) ..."
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES up -d

if [ "$needs_issuance" = 1 ]; then
  echo "### Requesting the real Let's Encrypt certificate via HTTP-01 ..."
  staging_flag=""
  if [ "${CERTBOT_STAGING:-0}" = "1" ]; then
    echo "    (using the Let's Encrypt STAGING environment — cert will not be trusted)"
    staging_flag="--staging"
  fi
  # Drop the dummy before requesting the real cert (nginx already booted on it).
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES run --rm --entrypoint sh certbot -c "rm -rf '$LIVE_PATH'"
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES run --rm --entrypoint certbot certbot \
    certonly --webroot -w /var/www/certbot \
    -d "$CERTBOT_DOMAIN" --email "$CERTBOT_EMAIL" \
    --agree-tos --no-eff-email --non-interactive $staging_flag
  echo "### Reloading nginx onto the real certificate ..."
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES exec -T frontend nginx -s reload
fi

echo "### ApplicationStart complete."
