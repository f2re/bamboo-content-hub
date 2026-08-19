#!/usr/bin/env bash
set -euo pipefail
[ $# -eq 1 ] || { echo "Usage: $0 backups/file.tgz"; exit 2; }
cd "$(dirname "$0")/.."
./scripts/backup.sh >/dev/null
docker compose -f compose.yml stop bamboo || true
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
tar -xzf "$1" -C "$work"
[ -f "$work/bamboo.db" ] && cp "$work/bamboo.db" data/bamboo.db
rm -rf data/media && cp -a "$work/media" data/media
python - <<'PY'
import sqlite3
c=sqlite3.connect('data/bamboo.db');assert c.execute('pragma integrity_check').fetchone()[0]=='ok';c.close()
PY
docker compose -f compose.yml up -d bamboo
./scripts/smoke.sh
