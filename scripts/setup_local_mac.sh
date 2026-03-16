#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "python3.11 も python3 も見つかりません。" >&2
  exit 1
fi

"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium

if [ ! -f .env ]; then
  cp .env.example .env
fi

python -m scripts.init_db

echo "Mac ローカル実行の初期セットアップが完了しました。"
echo "必要なら .env を編集してから ./scripts/run_local.sh を実行してください。"
