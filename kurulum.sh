#!/usr/bin/env bash
# Makine İz kurulumu: Python sanal ortamı + kilitli paketler (pypi.org) + ön yüz (registry.npmjs.org)
set -euo pipefail
cd "$(dirname "$0")"
PY=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 veya üstü gerekli (https://www.python.org)."
  exit 1
fi
echo "Python: $("$PY" --version)"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --index-url https://pypi.org/simple -r requirements.lock.txt
if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js 18 veya üstü gerekli (https://nodejs.org)."
  exit 1
fi
(cd frontend && npm ci --registry=https://registry.npmjs.org/ --no-audit --no-fund && npm run build)
echo
echo "Kurulum tamam. Başlatmak için:  ./baslat.sh"
