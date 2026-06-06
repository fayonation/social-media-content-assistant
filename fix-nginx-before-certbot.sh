#!/usr/bin/env bash
# Fix nginx so certbot can run when a previous setup left a broken SSL vhost.
# Run on the server BEFORE: sudo certbot certonly --nginx -d YOUR_SUBDOMAIN
# Usage: sudo ./fix-nginx-before-certbot.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing .env — set APP_HOST first:"
  echo "  cp .env.example .env && nano .env"
  exit 1
fi

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/load-env.sh"
load_env_file .env

if [[ -z "${APP_HOST:-}" ]]; then
  echo "APP_HOST must be set in .env (e.g. social.example.com)"
  exit 1
fi

APP_PORT="${PORT:-8000}"
CERT="/etc/letsencrypt/live/${APP_HOST}/fullchain.pem"

if [[ -f "${CERT}" ]]; then
  echo "Cert already exists at ${CERT} — run: sudo ./setup.sh"
  exit 0
fi

site=""
if [[ -d /etc/nginx/sites-available ]] && [[ -d /etc/nginx/sites-enabled ]]; then
  site="/etc/nginx/sites-available/${APP_HOST}.conf"
  enabled="/etc/nginx/sites-enabled/${APP_HOST}.conf"
elif [[ -d /etc/nginx/conf.d ]]; then
  site="/etc/nginx/conf.d/${APP_HOST}.conf"
  enabled="${site}"
else
  echo "ERROR: No nginx sites-enabled or conf.d directory"
  exit 1
fi

echo "==> Writing temporary HTTP-only vhost (no SSL) for ${APP_HOST}"
cat >"${site}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${APP_HOST};

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
        default_type "text/plain";
    }

    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

mkdir -p /var/www/letsencrypt/.well-known/acme-challenge

if [[ -d /etc/nginx/sites-enabled ]]; then
  ln -sf "${site}" "${enabled}"
fi

nginx -t
systemctl reload nginx

echo ""
echo "==> Nginx is valid. Before certbot, in Hostinger DNS for ${APP_HOST}:"
echo "  - A record -> this VPS IPv4"
echo "  - DELETE any AAAA (IPv6) record unless it points to THIS server"
echo "  (Let's Encrypt failed with 404 when IPv6 pointed at Hostinger.)"
echo ""
echo "Then:"
echo "  sudo certbot certonly --nginx -d ${APP_HOST}"
echo "  sudo ./setup.sh"
