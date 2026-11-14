#!/usr/bin/env bash
# Build the web app and deploy Kello to Fly.io (app kello-care, region arn, one always-on machine).
#
#   deploy/fly.sh            build app/web from source into deploy/dist, then deploy
#   deploy/fly.sh --dist     ship app/web/dist as it is (no build)
#   deploy/fly.sh --secrets  only (re)send the configured keys to Fly
#
# Needs flyctl and FLY_API_TOKEN. The deployment receives OXYLABS_API_KEY and
# GEMINI_API_KEY (JUNCTION_OXYLABS_API_KEY and JUNCTION_GEMINI_API_KEY remain
# accepted aliases), and MONGODB_URI when it is set. No key is printed or written to a file.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${KELLO_LOCAL:-}" && -f "$SCRIPT_DIR/fly.local.sh" ]]; then
  exec "$SCRIPT_DIR/fly.local.sh" "$@"
fi
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP="${FLY_APP:-kello-care}"
ORG="${FLY_ORG:-}"
MODE="${1:-build}"
cd "$ROOT"

fly() { flyctl "$@"; }

send_secrets() {
  : "${FLY_API_TOKEN:?set FLY_API_TOKEN}"
  local oxylabs="${OXYLABS_API_KEY:-${JUNCTION_OXYLABS_API_KEY:-}}"
  local gemini="${JUNCTION_GEMINI_API_KEY:-${GEMINI_API_KEY:-}}"
  : "${oxylabs:?set OXYLABS_API_KEY or JUNCTION_OXYLABS_API_KEY}"
  : "${gemini:?set GEMINI_API_KEY or JUNCTION_GEMINI_API_KEY}"
  # Optional: MongoDB Atlas (search over the quoted sentences, every live run kept). Without it the files answer.
  local mongo="${MONGODB_URI:-${JUNCTION_MONGODB_URI:-}}"
  local extra=()
  [[ -n "$mongo" ]] && extra+=("MONGODB_URI=$mongo")
  fly secrets set -a "$APP" "JUNCTION_OXYLABS_API_KEY=$oxylabs" "JUNCTION_GEMINI_API_KEY=$gemini" ${extra[@]+"${extra[@]}"} >/dev/null
  echo "secrets staged for $APP"
}

if ! fly status -a "$APP" >/dev/null 2>&1; then
  if [[ -n "$ORG" ]]; then
    fly apps create "$APP" --org "$ORG"
  else
    fly apps create "$APP"
  fi
fi
send_secrets
[[ "$MODE" == "--secrets" ]] && { fly secrets deploy -a "$APP"; exit 0; }

mkdir -p deploy/dist
if [[ "$MODE" == "--dist" ]]; then
  [[ -f app/web/dist/index.html ]] || { echo "app/web/dist is missing; run without --dist" >&2; exit 1; }
  rsync -a --delete app/web/dist/ deploy/dist/
else
  (cd app/web && pnpm install --silent && pnpm exec tsc --noEmit \
     && pnpm exec vite build --outDir "$ROOT/deploy/dist" --emptyOutDir)
fi

fly deploy --app "$APP" --config fly.toml --ha=false --wait-timeout 300
echo "https://$APP.fly.dev/#/plan/21"
