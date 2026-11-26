#!/usr/bin/env bash
# Throw-away PostgreSQL (+ PostgREST) for tests on a shared machine.
#   PostgreSQL : Unix socket only, in a directory only this account can enter (0700). No TCP listener.
#   PostgREST  : Unix socket in the same directory.
#   REST proxy : 127.0.0.1 only (supabase-py needs an http URL); every request needs a token signed with a secret that is
#                created for this run, kept in a 0600 file and never printed. Without one of this run's keys the proxy answers 401.
#
#   scripts/scratch_db.sh start DIR     # DIR must not exist or be a directory made by this script
#   source DIR/env                      # PATH, PSQL, SCH_IT_* for the tests
#   scripts/scratch_db.sh stop DIR      # stops everything and deletes DIR
#
# Needs: PG_BIN (directory of initdb / pg_ctl / psql with pgvector), POSTGREST (binary, optional), PYTHON (with httpx).
set -euo pipefail
umask 077
cmd="${1:?start|stop}"; dir="${2:?directory}"
root="$(cd "$(dirname "$0")/.." && pwd)"
PG_BIN="${PG_BIN:-$(dirname "$(command -v pg_ctl || echo /nonexistent/x)")}"
case "$cmd" in
start)
  [ -e "$dir" ] && [ ! -f "$dir/.scratch_db" ] && { echo "$dir exists and was not made by this script" >&2; exit 1; }
  mkdir -p "$dir"; chmod 700 "$dir"; dir="$(cd "$dir" && pwd)"; touch "$dir/.scratch_db"
  mkdir -p "$dir/sock"; chmod 700 "$dir/sock"
  if [ ! -d "$dir/data" ]; then
    "$PG_BIN/initdb" -D "$dir/data" -U postgres -A peer -E UTF8 --no-locale >/dev/null
    # the socket directory is private: local connections of this account only; nothing else is listed
    printf 'local all all trust\n' > "$dir/data/pg_hba.conf"
    cat >> "$dir/data/postgresql.conf" <<C
listen_addresses = ''
unix_socket_directories = '$dir/sock'
unix_socket_permissions = 0700
port = 54329
log_connections = on
log_disconnections = on
C
  fi
  "$PG_BIN/pg_ctl" -D "$dir/data" -l "$dir/pg.log" -w start >/dev/null
  psql="$PG_BIN/psql -h $dir/sock -p 54329 -U postgres"
  [ "$($psql -At -c 'show listen_addresses')" = "" ] || { echo "refusing: PostgreSQL listens on TCP" >&2; exit 1; }
  secret="$(head -c 48 /dev/urandom | base64 | tr -d '+/=\n')"
  anon="$(head -c 24 /dev/urandom | base64 | tr -d '+/=\n')"
  { echo "export PATH='$PG_BIN':\$PATH LC_ALL=C.UTF-8"; echo "export PSQL='$psql'"; } > "$dir/env"
  if [ -n "${POSTGREST:-}" ]; then
    cat > "$dir/postgrest.conf" <<C
db-uri = "postgres://authenticator@/hub?host=$dir/sock&port=54329"
db-schemas = "public"
db-extra-search-path = "public, extensions"
db-anon-role = "anon"
jwt-secret = "$secret"
server-unix-socket = "$dir/sock/postgrest.sock"
server-unix-socket-mode = "600"
C
    port="$("${PYTHON:-python3}" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
    { echo "export SCH_IT_REST_URL=http://127.0.0.1:$port SCH_IT_JWT_SECRET='$secret' SCH_IT_ANON_KEY='$anon'"
      echo "export SCH_IT_PSQL='$psql -d hub -q -t -A'"; } >> "$dir/env"
    (PSQL="$psql" PATH="$PG_BIN:$PATH" "$root/scripts/run_sql_tests.sh" hub > "$dir/sql_tests.log" 2>&1) || { tail -5 "$dir/sql_tests.log" >&2; exit 1; }
    "$POSTGREST" "$dir/postgrest.conf" > "$dir/postgrest.log" 2>&1 & echo $! > "$dir/postgrest.pid"
    SCH_IT_JWT_SECRET="$secret" SCH_IT_ANON_KEY="$anon" "${PYTHON:-python3}" "$root/scripts/dev_rest_proxy.py" --listen "$port" \
      --target-socket "$dir/sock/postgrest.sock" > "$dir/proxy.log" 2>&1 & echo $! > "$dir/proxy.pid"
    sleep 3
  fi
  echo "started: source $dir/env";;
stop)
  [ -f "$dir/.scratch_db" ] || { echo "$dir was not made by this script" >&2; exit 1; }
  for p in proxy postgrest; do [ -f "$dir/$p.pid" ] && kill "$(cat "$dir/$p.pid")" 2>/dev/null || true; done
  [ -f "$dir/data/postmaster.pid" ] && "$PG_BIN/pg_ctl" -D "$dir/data" -m fast stop >/dev/null || true
  rm -rf -- "$dir"; echo "stopped and deleted $dir";;
*) echo "start|stop" >&2; exit 1;;
esac
