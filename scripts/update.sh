#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[ -z "$(git status --porcelain)" ] || { echo "Есть локальные изменения; обновление остановлено."; exit 1; }
./scripts/backup.sh
git fetch origin main
git merge --ff-only origin/main
docker compose -f compose.yml build bamboo
docker compose -f compose.yml run --rm bamboo alembic upgrade head
docker compose -f compose.yml up -d bamboo
./scripts/smoke.sh
