#!/usr/bin/env bash
set -euo pipefail
url=${APP_BASE_URL:-http://localhost:${BAMBOO_PORT:-8080}}
curl -fsS "$url/health/ready" | grep -q ready
