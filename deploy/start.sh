#!/usr/bin/env bash
# Container entry point (Fly.io). Keys arrive as Fly secrets; nothing is printed.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# Only the Junction-issued Gemini key is used (the reader and the fallback agent); any other GEMINI_API_KEY is ignored.
export GEMINI_API_KEY="${JUNCTION_GEMINI_API_KEY:-}"
# A visitor's live web check never replaces a stored answer: every screen and every visitor sees the same plan.
export KELLO_VERIFY_PIN=1
exec uvicorn main:app --app-dir app/server --host 0.0.0.0 --port "${PORT:-8080}" --proxy-headers --forwarded-allow-ips '*'
