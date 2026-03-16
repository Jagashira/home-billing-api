#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -d .venv ]; then
  echo ".venv がありません。先に ./scripts/setup_local_mac.sh を実行してください。" >&2
  exit 1
fi

. .venv/bin/activate
python -m scripts.init_db

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

exec uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
