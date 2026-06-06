#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Missing .venv — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

PORT="${PORT:-8000}"
exec .venv/bin/python -m uvicorn app:app --reload --port "$PORT"
