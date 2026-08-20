#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."

[ -z "$(git status --porcelain)" ] || {
  echo "Есть локальные изменения; обновление остановлено." >&2
  exit 1
}

old_sha=$(git rev-parse HEAD)
backup_rel=$(./scripts/backup.sh | tail -n1)
backup_path=$(realpath "$backup_rel")
[ -f "$backup_path" ] || {
  echo "Не удалось создать резервную копию перед обновлением." >&2
  exit 1
}

wait_ready() {
  port=${BAMBOO_PORT:-}
  if [ -z "$port" ] && [ -f .env ]; then
    port=$(sed -n 's/^BAMBOO_PORT=//p' .env | tail -n1 | tr -d '\r' || true)
  fi
  port=${port:-8080}
  url=${BAMBOO_SMOKE_URL:-http://127.0.0.1:${port}/health/ready}
  for _attempt in $(seq 1 30); do
    if body=$(curl -fsS --connect-timeout 3 --max-time 5 "$url" 2>/dev/null) && grep -q 'ready' <<<"$body"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

rollback() {
  status=${1:-1}
  trap - ERR INT TERM
  set +e

  echo "Обновление не завершено. Возвращаю код и данные к $old_sha ..." >&2
  docker compose -f compose.yml stop bamboo >/dev/null 2>&1 || true

  work=$(mktemp -d)
  if tar -xzf "$backup_path" -C "$work"; then
    mkdir -p data
    rm -f data/bamboo.db data/bamboo.db-wal data/bamboo.db-shm
    [ ! -f "$work/bamboo.db" ] || cp "$work/bamboo.db" data/bamboo.db
    rm -rf data/media
    cp -a "$work/media" data/media 2>/dev/null || mkdir -p data/media
    if [ -f data/bamboo.db ]; then
      python - <<'PY'
import sqlite3

connection = sqlite3.connect('data/bamboo.db')
result = connection.execute('pragma integrity_check').fetchone()[0]
connection.close()
if result != 'ok':
    raise SystemExit(f'Rollback SQLite integrity check failed: {result}')
PY
    fi
  else
    echo "КРИТИЧЕСКАЯ ОШИБКА: не удалось распаковать $backup_path" >&2
  fi
  rm -rf "$work"

  git reset --hard "$old_sha" >/dev/null 2>&1 || true
  docker compose -f compose.yml build bamboo >/dev/null 2>&1 || true
  docker compose -f compose.yml up -d bamboo >/dev/null 2>&1 || true

  if wait_ready; then
    echo "Откат завершён. Рабочая версия: $old_sha" >&2
  else
    echo "КРИТИЧЕСКАЯ ОШИБКА: автоматический откат выполнен не полностью." >&2
    echo "Резервная копия сохранена: $backup_path" >&2
    echo "Выполните: ./scripts/restore.sh '$backup_path'" >&2
  fi
  exit "$status"
}

trap 'rollback $?' ERR
trap 'rollback 130' INT TERM

echo "Резервная копия: $backup_path"
echo "Обновляю $old_sha -> origin/main"
git fetch origin main
git merge --ff-only origin/main

docker compose -f compose.yml build bamboo
docker compose -f compose.yml run --rm bamboo alembic upgrade head
docker compose -f compose.yml up -d bamboo
./scripts/smoke.sh

trap - ERR INT TERM
new_sha=$(git rev-parse HEAD)
echo "Обновление завершено: $old_sha -> $new_sha"
