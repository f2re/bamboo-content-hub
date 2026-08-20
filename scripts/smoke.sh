#!/usr/bin/env bash
set -Eeuo pipefail

url=${APP_BASE_URL:-http://localhost:${BAMBOO_PORT:-8080}}

ready_payload="$(curl -fsS "$url/health/ready")"
grep -q '"status":"ready"' <<<"$ready_payload"

version_payload="$(curl -fsS "$url/health/version")"
grep -q '"feature_marker":"manual-first-browser-assist"' <<<"$version_payload"

printf '[Bamboo smoke] ready: %s\n' "$ready_payload"
printf '[Bamboo smoke] version: %s\n' "$version_payload"
