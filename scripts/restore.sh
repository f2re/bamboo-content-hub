#!/usr/bin/env bash
set -euo pipefail
[ $# -eq 1 ] || { echo "Usage: $0 backups/file.tgz"; exit 2; }
cd "$(dirname "$0")/.."

archive=$1
[ -f "$archive" ] || { echo "Backup not found: $archive" >&2; exit 2; }

tar -tzf "$archive" >/dev/null
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
tar -xzf "$archive" -C "$work"

if [ -f "$work/bamboo.db" ]; then
  python - "$work/bamboo.db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
result = connection.execute('pragma integrity_check').fetchone()[0]
connection.close()
if result != 'ok':
    raise SystemExit(f'Backup SQLite integrity check failed: {result}')
PY
fi

safety_backup=$(./scripts/backup.sh | tail -n1)
echo "Safety backup before restore: $safety_backup"
docker compose -f compose.yml stop bamboo || true

mkdir -p data
rm -f data/bamboo.db data/bamboo.db-wal data/bamboo.db-shm
if [ -f "$work/bamboo.db" ]; then
  cp "$work/bamboo.db" data/bamboo.db
fi
rm -rf data/media
cp -a "$work/media" data/media 2>/dev/null || mkdir -p data/media

if [ -f data/bamboo.db ]; then
  python - <<'PY'
import sqlite3

connection = sqlite3.connect('data/bamboo.db')
result = connection.execute('pragma integrity_check').fetchone()[0]
connection.close()
if result != 'ok':
    raise SystemExit(f'Restored SQLite integrity check failed: {result}')
PY
fi

docker compose -f compose.yml up -d bamboo
./scripts/smoke.sh
echo "Restore completed: $archive"
