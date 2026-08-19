#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || cp .env.example .env

read -r -s -p "Новый пароль администратора (минимум 12 символов): " password
echo
read -r -s -p "Повторите пароль: " confirm
echo

[ "$password" = "$confirm" ] || { echo "Пароли не совпадают." >&2; exit 1; }
[ "${#password}" -ge 12 ] || { echo "Пароль слишком короткий." >&2; exit 1; }

hash=""
if [ -x .venv/bin/python ]; then
  hash=$(printf '%s\n' "$password" | .venv/bin/python -c 'import sys; from app.security import hash_admin_password; print(hash_admin_password(sys.stdin.readline().rstrip("\n")))')
elif python3 -c 'import argon2' >/dev/null 2>&1; then
  hash=$(printf '%s\n' "$password" | python3 -c 'import sys; from app.security import hash_admin_password; print(hash_admin_password(sys.stdin.readline().rstrip("\n")))')
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  hash=$(printf '%s\n' "$password" | docker compose -f compose.yml run --rm -T bamboo python -c 'import sys; from app.security import hash_admin_password; print(hash_admin_password(sys.stdin.readline().rstrip("\n")))')
else
  echo "Не найден Python с argon2 и Docker Compose. Сначала установите/обновите Bamboo." >&2
  exit 1
fi
unset password confirm

[ -n "$hash" ] || { echo "Не удалось сформировать Argon2 hash." >&2; exit 1; }

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
awk -v hash="$hash" '
BEGIN { done=0 }
/^ADMIN_PASSWORD_HASH=/ { print "ADMIN_PASSWORD_HASH=" hash; done=1; next }
{ print }
END { if (!done) print "ADMIN_PASSWORD_HASH=" hash }
' .env > "$tmp"
mv "$tmp" .env
trap - EXIT
chmod 600 .env 2>/dev/null || true

echo "ADMIN_PASSWORD_HASH обновлён."
echo "Для защищённого внешнего режима также задайте APP_BASE_URL=https://... и TRUSTED_LAN=false."
