#!/usr/bin/env bash
# Makine İz'i başlatır → http://127.0.0.1:8000  (durdurmak için Ctrl+C)
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Önce kurulum yapın:  ./kurulum.sh"
  exit 1
fi
if [ ! -f frontend/dist/index.html ]; then
  echo "Ön yüz derleniyor…"
  (cd frontend && npm run build)
fi
PORT="${PORT:-8000}"
echo "Makine İz başlıyor: http://127.0.0.1:${PORT}   (durdurmak için Ctrl+C)"
cd backend
exec ../.venv/bin/python -m uvicorn --factory makine_iz.api:create_app --host 127.0.0.1 --port "${PORT}"
