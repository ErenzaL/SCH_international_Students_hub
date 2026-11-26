#!/usr/bin/env bash
# Apply shim + migrations + seed to a SCRATCH local PostgreSQL (with pgvector) and run the SQL behaviour tests.
# Usage: PSQL="psql -h localhost -p 5432 -U postgres" ./scripts/run_sql_tests.sh scratch_db_name
# WARNING: drops and recreates the named database. Never point this at a real/Supabase database.
set -euo pipefail
DB="${1:?scratch database name}"
PSQL="${PSQL:-psql}"
cd "$(dirname "$0")/.."
# a passwordless TCP listener would let every account of this machine become superuser of the test database
if [ "$($PSQL -At -c "select count(*) from pg_hba_file_rules where auth_method = 'trust' and type like 'host%' and current_setting('listen_addresses') <> ''")" != "0" ]; then
  echo "refusing: this PostgreSQL accepts TCP connections without a password (use scripts/scratch_db.sh)" >&2; exit 1
fi
$PSQL -q -c "drop database if exists \"$DB\"" -c "create database \"$DB\""
for f in scripts/local_supabase_shim.sql supabase/migrations/*.sql supabase/seed.sql; do
  echo "applying $f"; $PSQL -q -v ON_ERROR_STOP=1 -d "$DB" -f "$f"
done
export PGOPTIONS="${PGOPTIONS:-} -c client_min_messages=warning"
for t in supabase/tests/behavior_test*.sql; do $PSQL -q -t -A -d "$DB" -f "$t" | tail -1; done
