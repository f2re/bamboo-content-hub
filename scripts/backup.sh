#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
stamp=$(date +%Y%m%d-%H%M%S); work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
if [ -f data/bamboo.db ]; then python - "$work/bamboo.db" <<'PY'
import sqlite3,sys
src=sqlite3.connect('data/bamboo.db');dst=sqlite3.connect(sys.argv[1]);src.backup(dst);dst.close();src.close()
PY
fi
cp -a data/media "$work/media" 2>/dev/null || mkdir -p "$work/media"
tar -C "$work" -czf "backups/bamboo-$stamp.tgz" .
echo "backups/bamboo-$stamp.tgz"
