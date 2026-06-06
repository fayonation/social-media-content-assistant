#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Missing .venv — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f assets/fonts/NotoSans.ttf || ! -f assets/fonts/NotoNaskhArabic.ttf ]]; then
  chmod +x scripts/download-fonts.sh 2>/dev/null || true
  ./scripts/download-fonts.sh
fi

PORT="${PORT:-8000}"
exec .venv/bin/python -m uvicorn app:app --reload --port "$PORT"
