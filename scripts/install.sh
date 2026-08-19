#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { cp .env.example .env; python - <<'PY'
from pathlib import Path
import secrets
p=Path('.env');s=p.read_text();s=s.replace('replace-with-long-random-value',secrets.token_urlsafe(48),1).replace('replace-with-separate-long-random-value',secrets.token_urlsafe(48),1);p.write_text(s)
PY
}
mkdir -p data/media
docker compose -f compose.yml up -d --build
echo "Bamboo Content Hub: http://localhost:${BAMBOO_PORT:-8080}"
