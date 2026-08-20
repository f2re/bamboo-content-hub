#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

log() {
  printf '\n[Bamboo update] %s\n' "$*"
}

fail() {
  printf '\n[Bamboo update] ОШИБКА: %s\n' "$*" >&2
  exit 1
}

command -v git >/dev/null 2>&1 || fail "Не найден git"
command -v docker >/dev/null 2>&1 || fail "Не найден Docker"
docker compose version >/dev/null 2>&1 || fail "Не найден Docker Compose v2"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "Скрипт запущен не из Git-репозитория"

branch="$(git symbolic-ref --quiet --short HEAD || true)"
if [[ "$branch" != "main" ]]; then
  fail "Для автоматического обновления переключитесь на ветку main (сейчас: ${branch:-detached HEAD})"
fi

dirty="$(git status --porcelain --untracked-files=normal)"
if [[ -n "$dirty" ]]; then
  printf '\n[Bamboo update] Обновление остановлено: найдены локальные изменения.\n' >&2
  printf '[Bamboo update] Файлы не будут сброшены или удалены автоматически:\n\n' >&2
  git status --short --untracked-files=normal >&2
  cat >&2 <<'EOF'

Сохраните изменения одним из безопасных способов:
  • закоммитьте их;
  • либо временно уберите: git stash push -u -m "before Bamboo update";
  • либо удалите только заведомо ненужные файлы вручную.

Не используйте git reset --hard или git clean, пока не проверили список выше.
EOF
  exit 2
fi

log "Создаю резервную копию данных и медиа"
backup_path="$(./scripts/backup.sh | tail -n 1)"
printf '[Bamboo update] Резервная копия: %s\n' "$backup_path"

log "Загружаю актуальный main"
git fetch --prune origin main
git merge --ff-only origin/main

log "Пересобираю приложение"
docker compose -f compose.yml build bamboo

log "Применяю миграции базы данных"
docker compose -f compose.yml run --rm bamboo alembic upgrade head

log "Перезапускаю Bamboo Content Hub"
docker compose -f compose.yml up -d bamboo

log "Проверяю готовность"
./scripts/smoke.sh

log "Обновление завершено"
