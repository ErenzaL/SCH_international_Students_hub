#!/usr/bin/env bash
# Local staging on ONE PERSON'S computer (MacBook): the real Supabase stack (Postgres + pgvector, Auth, PostgREST, Storage, RLS) from the
# Supabase CLI in Docker, bound to 127.0.0.1 only, with the Hub's migrations, synthetic seed and made-up accounts. $0, no hosted project.
# Not for a shared server: other accounts could reach the stack's database with its well-known local password.
#
#   scripts/local_supabase.sh check       # software, Docker engine, not linked to a hosted project
#   scripts/local_supabase.sh up          # start the stack (loopback only), migrations + seed, made-up accounts, info file
#   scripts/local_supabase.sh api         # the Hub API against the stack, official websites synthetic (foreground; another terminal)
#                                         # LLM_PROVIDER=ollama for Qwen (Ollama on this computer); default none
#   scripts/local_supabase.sh web         # the web app against the stack (foreground; another terminal)
#   scripts/local_supabase.sh test        # SQL behaviour tests + backend integration tests against the stack, then accounts again
#   scripts/local_supabase.sh e2e [JOURNEYS]   # browser journeys (needs api + web running)
#   scripts/local_supabase.sh memory      # hosted-style memory check against the local API
#   scripts/local_supabase.sh down        # stop (data kept);  down --wipe  deletes the local data
#
# Never runs `supabase link`, `db push` or anything with --linked; refuses a checkout that is linked to a hosted project, and unsets
# the Supabase access token for every command. Private files: ~/.sch-local (mode 700).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRIV="${SCH_LOCAL_DIR:-$HOME/.sch-local}"
NET=sch-hub-local
PY="$ROOT/backend/.venv/bin/python"
unset SUPABASE_ACCESS_TOKEN SUPABASE_DB_PASSWORD SUPABASE_PROJECT_ID SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY SUPABASE_JWT_SECRET 2>/dev/null || true
die() { echo "REFUSED: $*" >&2; exit 1; }
cd "$ROOT"
mkdir -p "$PRIV/run"; chmod 700 "$PRIV"
[ -e "$PRIV/.env" ] || [ -e "$PRIV/run/.env" ] && die "$PRIV must not contain a .env file (the API would read it)"

linked_check() {
  [ -f supabase/.temp/project-ref ] && die "this checkout is linked to a hosted Supabase project (supabase/.temp/project-ref). Use a fresh clone for local staging."
  return 0
}

load_env() {
  [ -f "$PRIV/stack.env" ] || die "run '$0 up' first"
  # shellcheck disable=SC1091
  set -a; . "$PRIV/stack.env"; set +a
  SERVICE_KEY="${SECRET_KEY:-${SERVICE_ROLE_KEY:-}}"; PUBLIC_KEY="${PUBLISHABLE_KEY:-${ANON_KEY:-}}"
  for v in API_URL DB_URL; do [ -n "${!v:-}" ] || die "supabase status did not report $v"; done
  case "$API_URL$DB_URL" in *supabase.co*|*supabase.com*|*onrender.com*) die "the stack reports a hosted address";; esac
  case "$API_URL" in http://127.0.0.1:*|http://localhost:*) ;; *) die "API_URL is not on this computer: $API_URL";; esac
}

case "${1:-}" in
check)
  linked_check
  for c in supabase docker psql node npm; do command -v $c >/dev/null || die "missing: $c (see docs/owner/STAGING.md, software)"; done
  [ -x "$PY" ] || die "missing backend/.venv (cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt)"
  docker info >/dev/null 2>&1 || die "the Docker engine does not answer (start Colima: colima start --cpu 4 --memory 8)"
  echo "ok: supabase $(supabase --version), $(docker version --format 'docker {{.Server.Version}}' 2>/dev/null), $(psql --version)";;
up)
  linked_check
  docker network inspect $NET >/dev/null 2>&1 || docker network create -o com.docker.network.bridge.host_binding_ipv4=127.0.0.1 $NET >/dev/null
  if [ ! -f supabase/config.toml ]; then
    supabase init </dev/null >/dev/null
    "$PY" - <<'PYEOF'
import re
from pathlib import Path
p = Path("supabase/config.toml"); t = p.read_text()
t = re.sub(r'(?m)^project_id = ".*"$', 'project_id = "sch-hub-local"', t, count=1)
t = re.sub(r'(?m)^site_url = ".*"$', 'site_url = "http://127.0.0.1:3000"', t, count=1)
t = re.sub(r'(?m)^additional_redirect_urls = \[.*\]$', 'additional_redirect_urls = ["http://127.0.0.1:3000", "http://localhost:3000"]', t, count=1)
p.write_text(t)
PYEOF
  fi
  supabase start --network-id $NET
  # every published port must be on 127.0.0.1 only
  if docker ps --format '{{.Names}} {{.Ports}}' | grep '^supabase_' | grep -E '0\.0\.0\.0:|:::|\[::\]:' ; then
    supabase stop >/dev/null; die "a Supabase container is published on all interfaces (above); stopped. Recreate the network: docker network rm $NET"
  fi
  (umask 077; supabase status -o env > "$PRIV/stack.env")
  load_env
  STAGING_SUPABASE_URL="$API_URL" STAGING_DB_URL="$DB_URL" STAGING_SERVICE_KEY="$SERVICE_KEY" STAGING_ANON_KEY="$PUBLIC_KEY" \
  STAGING_API=http://127.0.0.1:8051 STAGING_WEB=http://127.0.0.1:3000 STAGING_CRON_SECRET="$(openssl rand -hex 24)" \
    "$PY" scripts/staging_bootstrap.py all --supabase-local --info "$PRIV/sch-local.json"
  grep -o '"cron": "[^"]*"' "$PRIV/sch-local.json" | cut -d'"' -f4 > "$PRIV/cron"; chmod 600 "$PRIV/cron"
  echo "local stack up: API $API_URL, Studio ${STUDIO_URL:-http://127.0.0.1:54323}; accounts and password in $PRIV/sch-local.json";;
api)
  load_env
  [ -d "$ROOT/backend/.model-cache" ] || (cd "$PRIV/run" && EMBEDDING_CACHE_DIR="$ROOT/backend/.model-cache" PYTHONPATH="$ROOT/backend" "$PY" -m app.cli prefetch-model)
  # from an empty directory (no .env is read) and with every production-sensitive variable set empty
  cd "$PRIV/run"
  exec env SUPABASE_URL="$API_URL" SUPABASE_SERVICE_ROLE_KEY="$SERVICE_KEY" SUPABASE_JWT_SECRET="${JWT_SECRET:-}" \
    ENVIRONMENT=local-staging CORS_ORIGINS=http://127.0.0.1:3000 JOB_EXECUTION=worker MALLOC_ARENA_MAX=2 \
    EMBEDDING_PROVIDER=e5_onnx EMBEDDING_CACHE_DIR="$ROOT/backend/.model-cache" RETRIEVAL_MIN_SIMILARITY=0.80 \
    LLM_PROVIDER="${LLM_PROVIDER:-none}" LLM_API_KEY= GEMINI_API_KEY= GOOGLE_API_KEY= OCR_SPACE_API_KEY= CRON_SECRET="$(cat "$PRIV/cron")" \
    GPU_WORKER_ENABLED="${GPU_WORKER_ENABLED:-true}" AGENT_SCHEDULES_ENABLED="${AGENT_SCHEDULES_ENABLED:-true}" AUTO_TRANSLATE_ANNOUNCEMENTS=false \
    AUTO_TRANSLATE_DOCUMENTS=false PUBLIC_MACHINE_TRANSLATIONS=false \
    "$PY" -m uvicorn local_api:app --app-dir "$ROOT/scripts" --host 127.0.0.1 --port 8051;;
web)
  load_env
  cd "$ROOT/apps/web"
  export NEXT_PUBLIC_SITE_ENV=staging NEXT_PUBLIC_SUPABASE_URL="$API_URL" NEXT_PUBLIC_SUPABASE_ANON_KEY="$PUBLIC_KEY" NEXT_PUBLIC_API_URL=http://127.0.0.1:8051 NEXT_TELEMETRY_DISABLED=1
  [ -d node_modules ] || npm ci
  npx next build && exec npx next start -H 127.0.0.1 -p 3000;;
test)
  load_env
  export PGOPTIONS="-c client_min_messages=warning"
  for t in supabase/tests/behavior_test*.sql; do psql "$DB_URL" -q -t -A -v ON_ERROR_STOP=1 -f "$t" | tail -1; done
  (cd backend && SCH_IT_REST_URL="$API_URL" SCH_IT_PSQL="psql $DB_URL -q -t -A" SCH_IT_JWT_SECRET="${JWT_SECRET:?the stack reported no JWT_SECRET}" \
     SCH_IT_ANON_KEY="${ANON_KEY:-$PUBLIC_KEY}" .venv/bin/python -m pytest -q -p no:cacheprovider tests/integration)
  # the integration tests write their own rows; refresh the made-up accounts for the browser journeys
  STAGING_SUPABASE_URL="$API_URL" STAGING_DB_URL="$DB_URL" STAGING_SERVICE_KEY="$SERVICE_KEY" STAGING_ANON_KEY="$PUBLIC_KEY" \
  STAGING_API=http://127.0.0.1:8051 STAGING_WEB=http://127.0.0.1:3000 STAGING_CRON_SECRET="$(cat "$PRIV/cron")" \
    "$PY" scripts/staging_bootstrap.py info --supabase-local --info "$PRIV/sch-local.json";;
e2e)
  load_env
  [ -d "$PRIV/pw/node_modules/playwright" ] || (mkdir -p "$PRIV/pw" && cd "$PRIV/pw" && npm init -y >/dev/null && npm i playwright@1 >/dev/null && npx playwright install chromium)
  # the official websites are synthetic (local_api.py); visa, chats, gpu and the answers of announcement/pdf need Qwen (LLM_PROVIDER=ollama)
  if [ "${LLM_PROVIDER:-none}" = none ]; then DEF=setup,announcement,pdf,career,scholarship,escalation,admin,office,autonomy; export LLM=none
  else DEF=setup,announcement,pdf,visa,chats,career,scholarship,gpu,escalation,admin,office,autonomy; fi
  cd "$PRIV/pw" && PDF_PYTHON="$PY" ONLY="${2:-$DEF}" node "$ROOT/scripts/e2e_full.mjs" "$PRIV/sch-local.json" "$PRIV/e2e-out" \
    "$ROOT/backend/.venv/bin/python" "$ROOT/backend";;
memory)
  load_env
  (cd backend && .venv/bin/python ../scripts/staging_memory_check.py "$PRIV/sch-local.json" --report "$PRIV/memory-local.json" --pdf-dir "$PRIV/pdfs");;
down)
  if [ "${2:-}" = "--wipe" ]; then supabase stop --no-backup; else supabase stop; fi;;
*) sed -n '2,16p' "$0"; exit 1;;
esac
