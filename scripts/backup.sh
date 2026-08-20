#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p backups
stamp="$(date +%Y%m%d-%H%M%S)-$$"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if [ -f data/bamboo.db ]; then
  python - "$work/bamboo.db" <<'PY'
import sqlite3
import sys

src = sqlite3.connect('data/bamboo.db')
dst = sqlite3.connect(sys.argv[1])
src.backup(dst)
dst.close()
src.close()
PY
fi

cp -a data/media "$work/media" 2>/dev/null || mkdir -p "$work/media"
cat >"$work/backup-meta.txt" <<EOF
created_at=$(date -Iseconds)
git_sha=$(git rev-parse HEAD 2>/dev/null || echo unknown)
format=bamboo-backup-v1
EOF

archive="backups/bamboo-$stamp.tgz"
tar -C "$work" -czf "$archive" .
echo "$archive"
