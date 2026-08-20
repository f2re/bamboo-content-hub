#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  python - <<'PY'
from pathlib import Path
import secrets

path = Path('.env')
text = path.read_text()
text = text.replace('replace-with-long-random-value', secrets.token_urlsafe(48), 1)
text = text.replace('replace-with-separate-long-random-value', secrets.token_urlsafe(48), 1)
path.write_text(text)
PY
fi

mkdir -p data/media
docker compose -f compose.yml up -d --build
./scripts/smoke.sh

echo "Bamboo Content Hub установлен и готов: http://localhost:${BAMBOO_PORT:-8080}"
