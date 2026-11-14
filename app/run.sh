#!/usr/bin/env bash
# Start the Kello server (API + built frontend) on port 8742 with environment configuration.
#   app/run.sh            serve app/web/dist at / and the API at /api
#   app/run.sh --build    build the frontend first
#   PORT=9000 app/run.sh  another port
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${KELLO_LOCAL:-}" && -f "$SCRIPT_DIR/run.local.sh" ]]; then
  exec "$SCRIPT_DIR/run.local.sh" "$@"
fi
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
PORT="${PORT:-8742}"
HOST="${HOST:-0.0.0.0}"
UVICORN="$ROOT/.venv/bin/uvicorn"

if [[ "${1:-}" == "--build" ]]; then
  # pnpm reads app/web/pnpm-workspace.yaml, which allows esbuild's install script (without it pnpm 10+ stops with ERR_PNPM_IGNORED_BUILDS).
  if command -v pnpm >/dev/null 2>&1; then
    (cd "$ROOT/app/web" && pnpm install --silent && pnpm build)
  else
    (cd "$ROOT/app/web" && npm install --silent && npm run build)
  fi
fi
[[ -d "$ROOT/app/web/dist" ]] || echo "note: app/web/dist is missing; run app/run.sh --build" >&2

# The public launcher reads these names from the environment.  A deployment may
# provide JUNCTION_GEMINI_API_KEY; keep that compatibility alias for Gemini.
if [[ -n "${JUNCTION_GEMINI_API_KEY:-}" ]]; then
  export GEMINI_API_KEY="$JUNCTION_GEMINI_API_KEY"
fi
CMD=("$UVICORN" main:app --app-dir "$ROOT/app/server" --host "$HOST" --port "$PORT")
exec "${CMD[@]}"
