#!/usr/bin/env bash
# Show web server, ports, and app status (no changes).
# Run: ./diagnose.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/load-env.sh"
  load_env_file .env
fi

APP_PORT="${PORT:-8000}"
APP_HOST="${APP_HOST:-not-set-in-.env}"

echo "=== Config ==="
echo "APP_HOST=${APP_HOST}"
echo "PORT=${APP_PORT}"

echo ""
echo "=== Ports 80 / 443 (HTTPS front door) ==="
ss -tlnp 2>/dev/null | grep -E ':80 |:443 ' || true

echo ""
echo "=== App port (localhost) ==="
ss -tlnp 2>/dev/null | grep -E ":${APP_PORT} " || true

echo ""
echo "=== Web servers ==="
for svc in apache2 nginx; do
  if systemctl list-unit-files "${svc}.service" &>/dev/null; then
    printf "%-10s active=%s enabled=%s\n" "${svc}" \
      "$(systemctl is-active "${svc}" 2>/dev/null || echo '?')" \
      "$(systemctl is-enabled "${svc}" 2>/dev/null || echo '?')"
  else
    printf "%-10s not installed\n" "${svc}"
  fi
done

echo ""
echo "=== systemd app service ==="
if systemctl list-unit-files social-media-content-assistant.service &>/dev/null; then
  printf "social-media-content-assistant active=%s enabled=%s\n" \
    "$(systemctl is-active social-media-content-assistant 2>/dev/null || echo '?')" \
    "$(systemctl is-enabled social-media-content-assistant 2>/dev/null || echo '?')"
else
  echo "social-media-content-assistant.service not installed"
fi

echo ""
echo "=== Config dirs ==="
ls -la /etc/apache2/sites-available 2>/dev/null || echo "No /etc/apache2/sites-available"
ls -la /etc/nginx/sites-enabled 2>/dev/null || echo "No /etc/nginx/sites-enabled"

echo ""
echo "=== Docker (public ports — avoid conflicts) ==="
docker ps --format 'table {{.Names}}\t{{.Ports}}' 2>/dev/null || echo "docker not available"

echo ""
echo "=== App health ==="
curl -sI "http://127.0.0.1:${APP_PORT}/" 2>/dev/null | head -5 || echo "No response on 127.0.0.1:${APP_PORT}"

if [[ -f "/etc/letsencrypt/live/${APP_HOST}/fullchain.pem" ]]; then
  echo ""
  echo "TLS cert: /etc/letsencrypt/live/${APP_HOST}/fullchain.pem (OK)"
else
  echo ""
  echo "TLS cert: missing for ${APP_HOST} — run fix-nginx-before-certbot.sh then certbot"
fi
