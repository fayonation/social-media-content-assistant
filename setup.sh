#!/usr/bin/env bash
# Deploy Social Media Content Assistant on Ubuntu with Nginx/Apache + systemd.
# Prerequisite: TLS cert for APP_HOST (run certbot before this script).
# Run: sudo ./setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SERVICE_NAME="social-media-content-assistant"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "Created .env from .env.example — edit APP_HOST and REPLICATE_API_TOKEN:"
    echo "  nano .env"
    exit 1
  fi
  echo "Missing .env — create it with:"
  echo "  APP_HOST=your-subdomain.example.com"
  echo "  PORT=8000"
  echo "  REPLICATE_API_TOKEN=r8_your_token"
  exit 1
fi

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/load-env.sh"
load_env_file .env

if [[ -z "${APP_HOST:-}" ]]; then
  echo "APP_HOST must be set in .env (your subdomain, e.g. social.example.com)"
  exit 1
fi

APP_PORT="${PORT:-8000}"
CERT_DIR="/etc/letsencrypt/live/${APP_HOST}"

if [[ -z "${REPLICATE_API_TOKEN:-}" || "${REPLICATE_API_TOKEN}" == "r8_paste_your_token_here" ]]; then
  if [[ ! -f config.json ]] || grep -q 'r8_paste_your_token_here' config.json 2>/dev/null; then
    echo "Set REPLICATE_API_TOKEN in .env or replicate_api_token in config.json"
    exit 1
  fi
fi

if ss -tlnp 2>/dev/null | grep -q ":${APP_PORT} "; then
  if ! systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    echo "Port ${APP_PORT} is already in use by another process."
    ss -tlnp | grep ":${APP_PORT} " || true
    exit 1
  fi
fi

detect_proxy() {
  if [[ -n "${REVERSE_PROXY:-}" ]]; then
    echo "${REVERSE_PROXY}"
    return
  fi
  if [[ -d /etc/apache2/sites-available ]]; then
    echo "apache"
    return
  fi
  if [[ -d /etc/nginx/sites-available ]] || [[ -d /etc/nginx/conf.d ]]; then
    echo "nginx"
    return
  fi
  echo "none"
}

require_tls_cert() {
  if [[ ! -f "${CERT_DIR}/fullchain.pem" ]]; then
    echo "ERROR: No TLS cert at ${CERT_DIR}/fullchain.pem"
    echo "Run certbot first (DNS A record must point to this VPS):"
    if [[ "${PROXY}" == "nginx" ]]; then
      echo "  sudo ./fix-nginx-before-certbot.sh   # if nginx -t fails"
      echo "  sudo certbot certonly --nginx -d ${APP_HOST}"
    else
      echo "  sudo certbot certonly --apache -d ${APP_HOST}"
    fi
    echo "DNS: fix AAAA to your VPS IPv6 or remove it (wrong AAAA breaks certbot)."
    exit 1
  fi
}

PROXY="$(detect_proxy)"
NGINX_SITE_ENABLED=""

ensure_venv() {
  if ! python3 -c "import venv" 2>/dev/null; then
    echo "==> Installing python3-venv (required for virtualenv)"
    apt-get install -y python3-venv python3-pip
  fi

  if [[ -d .venv && ! -x .venv/bin/python ]]; then
    echo "==> Removing broken .venv"
    rm -rf .venv
  fi

  if [[ ! -x .venv/bin/python ]]; then
    echo "==> Creating Python virtualenv"
    python3 -m venv .venv
  fi

  if [[ ! -x .venv/bin/python ]]; then
    echo "ERROR: Could not create .venv/bin/python"
    echo "Try: apt install -y python3-venv python3-pip && sudo ./setup.sh"
    exit 1
  fi

  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements.txt
}

echo "==> Installing Python dependencies"
ensure_venv

if [[ ! -f config.json ]]; then
  cp config.example.json config.json
fi

chmod +x scripts/download-fonts.sh 2>/dev/null || true
if [[ ! -f assets/fonts/NotoSans.ttf || ! -f assets/fonts/NotoNaskhArabic.ttf ]]; then
  ./scripts/download-fonts.sh
fi

echo "==> Installing systemd service ${SERVICE_NAME}"
UNIT="/etc/systemd/system/${SERVICE_NAME}.service"
cat >"${UNIT}" <<EOF
[Unit]
Description=Social Media Content Assistant
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${SCRIPT_DIR}
EnvironmentFile=${SCRIPT_DIR}/.env
ExecStart=${SCRIPT_DIR}/.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port ${APP_PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

substitute_vhost() {
  local template="$1"
  local dest="$2"
  sed -e "s/__HOST__/${APP_HOST}/g" -e "s/__PORT__/${APP_PORT}/g" "${template}" >"${dest}"
}

install_apache() {
  require_tls_cert
  local site="/etc/apache2/sites-available/${APP_HOST}.conf"
  echo "==> Enabling Apache modules"
  a2enmod proxy proxy_http ssl headers rewrite 2>/dev/null || true

  echo "==> Installing Apache vhost for ${APP_HOST}"
  substitute_vhost "${SCRIPT_DIR}/apache/vhost.conf.template" "${site}"

  a2ensite "$(basename "${site}")"
  apache2ctl configtest
  systemctl reload apache2
}

install_nginx() {
  require_tls_cert
  local site=""
  local enabled=""

  if [[ -d /etc/nginx/sites-available ]] && [[ -d /etc/nginx/sites-enabled ]]; then
    site="/etc/nginx/sites-available/${APP_HOST}.conf"
    enabled="/etc/nginx/sites-enabled/${APP_HOST}.conf"
    substitute_vhost "${SCRIPT_DIR}/nginx/vhost.conf.template" "${site}"
    ln -sf "${site}" "${enabled}"
  elif [[ -d /etc/nginx/conf.d ]]; then
    site="/etc/nginx/conf.d/${APP_HOST}.conf"
    substitute_vhost "${SCRIPT_DIR}/nginx/vhost.conf.template" "${site}"
  else
    echo "ERROR: No /etc/nginx/sites-enabled or /etc/nginx/conf.d found"
    exit 1
  fi

  echo "==> Installing Nginx vhost for ${APP_HOST} -> ${site}"
  NGINX_SITE_ENABLED="${enabled}"

  nginx -t
  systemctl reload nginx
}

case "${PROXY}" in
  apache) install_apache ;;
  nginx) install_nginx ;;
  *)
    echo "ERROR: No Apache or Nginx found. Set REVERSE_PROXY=nginx in .env"
    echo "  ./diagnose.sh"
    exit 1
    ;;
esac

sleep 2
if ! curl -sfI "http://127.0.0.1:${APP_PORT}/" >/dev/null 2>&1; then
  echo ""
  echo "WARNING: App not responding on http://127.0.0.1:${APP_PORT}/"
  echo "Check: journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
fi

echo ""
echo "==> Deploy complete (${PROXY})"
echo "  Web UI:       https://${APP_HOST}"
echo "  Local app:    http://127.0.0.1:${APP_PORT}/"
echo "  Data:         ${SCRIPT_DIR}/social_studio.db + ${SCRIPT_DIR}/media/"
echo "  Service:      systemctl status ${SERVICE_NAME}"
if [[ -n "${NGINX_SITE_ENABLED}" ]]; then
  echo "  Nginx site:   ${NGINX_SITE_ENABLED}"
fi
echo "  Next:         open https://${APP_HOST} → Models → activate text + image models"
