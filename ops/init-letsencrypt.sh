#!/bin/sh
# One-time Let's Encrypt issuance bootstrap for PolicyFlow. Run ONCE on the host
# after DNS resolves to the EIP, before the prod stack can serve valid HTTPS. This
# is a sanctioned manual step (like authorizing the GitHub connection), not part of
# any deploy. Renewal afterwards is automatic via the in-stack certbot sidecar.
#
# Flow: nginx needs a cert file to boot, but the real cert needs a running nginx to
# answer the ACME HTTP-01 challenge. We break the chicken-and-egg with a throwaway
# self-signed dummy cert, boot nginx on it, then replace it with the real cert.
#
# Usage (from the repo root on the host):  ./ops/init-letsencrypt.sh
set -eu

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
ENVIRONMENT_FILE=".env"

if [ ! -f "$ENVIRONMENT_FILE" ]; then
  echo "Error: $ENVIRONMENT_FILE not found. Copy .env.example to .env and set the CERTBOT_* values first." >&2
  exit 1
fi

# Read CERTBOT_* from .env without leaking the rest of the environment.
CERTBOT_DOMAIN="$(grep -E '^CERTBOT_DOMAIN=' "$ENVIRONMENT_FILE" | cut -d= -f2-)"
CERTBOT_EMAIL="$(grep -E '^CERTBOT_EMAIL=' "$ENVIRONMENT_FILE" | cut -d= -f2-)"
CERTBOT_STAGING="$(grep -E '^CERTBOT_STAGING=' "$ENVIRONMENT_FILE" | cut -d= -f2-)"

if [ -z "${CERTBOT_DOMAIN:-}" ] || [ -z "${CERTBOT_EMAIL:-}" ]; then
  echo "Error: CERTBOT_DOMAIN and CERTBOT_EMAIL must be set in $ENVIRONMENT_FILE." >&2
  exit 1
fi

LIVE_PATH="/etc/letsencrypt/live/$CERTBOT_DOMAIN"

echo "### Downloading certbot's recommended TLS options into the letsencrypt volume ..."
# nginx.tls.conf includes these two files; place them before nginx first boots.
$COMPOSE run --rm --entrypoint "/bin/sh -c \"\
  curl -fsSL https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf \
    -o /etc/letsencrypt/options-ssl-nginx.conf && \
  curl -fsSL https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem \
    -o /etc/letsencrypt/ssl-dhparam.pem\"" certbot

echo "### Creating a temporary dummy self-signed certificate so nginx can boot ..."
$COMPOSE run --rm --entrypoint "/bin/sh -c \"\
  mkdir -p '$LIVE_PATH' && \
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout '$LIVE_PATH/privkey.pem' \
    -out '$LIVE_PATH/fullchain.pem' \
    -subj '/CN=localhost'\"" certbot

echo "### Starting nginx on the dummy certificate ..."
$COMPOSE up -d frontend

echo "### Deleting the dummy certificate before requesting the real one ..."
$COMPOSE run --rm --entrypoint "/bin/sh -c \"rm -rf '$LIVE_PATH'\"" certbot

echo "### Requesting the real Let's Encrypt certificate via HTTP-01 ..."
STAGING_FLAG=""
if [ "${CERTBOT_STAGING:-0}" = "1" ]; then
  echo "    (using the Let's Encrypt STAGING environment — cert will not be trusted by browsers)"
  STAGING_FLAG="--staging"
fi

$COMPOSE run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    -d '$CERTBOT_DOMAIN' \
    --email '$CERTBOT_EMAIL' \
    --agree-tos --no-eff-email --non-interactive \
    $STAGING_FLAG" certbot

echo "### Reloading nginx onto the real certificate ..."
$COMPOSE exec frontend nginx -s reload

echo "### Done. https://$CERTBOT_DOMAIN should now serve a valid certificate."
echo "    Renewal is automatic via the in-stack certbot sidecar; bring the full stack up with:"
echo "    $COMPOSE up -d"
