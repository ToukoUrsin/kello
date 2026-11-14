#!/usr/bin/env bash
# Container entry point (Fly.io). Keys arrive as Fly secrets; nothing is printed.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# The Junction-issued Gemini key is the one the reader and the fallback agent use.
if [[ -n "${JUNCTION_GEMINI_API_KEY:-}" ]]; then export GEMINI_API_KEY="$JUNCTION_GEMINI_API_KEY"; fi
exec uvicorn main:app --app-dir app/server --host 0.0.0.0 --port "${PORT:-8080}" --proxy-headers --forwarded-allow-ips '*'
