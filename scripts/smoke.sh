#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

port=${BAMBOO_PORT:-}
if [ -z "$port" ] && [ -f .env ]; then
  port=$(sed -n 's/^BAMBOO_PORT=//p' .env | tail -n1 | tr -d '\r' || true)
fi
port=${port:-8080}
url=${BAMBOO_SMOKE_URL:-http://127.0.0.1:${port}/health/ready}
attempts=${BAMBOO_SMOKE_ATTEMPTS:-30}
delay=${BAMBOO_SMOKE_DELAY_SECONDS:-2}

for ((attempt=1; attempt<=attempts; attempt++)); do
  if body=$(curl -fsS --connect-timeout 3 --max-time 5 "$url" 2>/dev/null) && grep -q 'ready' <<<"$body"; then
    echo "Bamboo Content Hub ready: $url"
    exit 0
  fi
  if (( attempt < attempts )); then
    sleep "$delay"
  fi
done

echo "Bamboo Content Hub did not become ready: $url" >&2
exit 1
