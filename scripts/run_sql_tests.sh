#!/usr/bin/env bash
# Apply shim + migrations + seed to a SCRATCH local PostgreSQL (with pgvector) and run the SQL behaviour tests.
# Usage: PSQL="psql -h localhost -p 5432 -U postgres" ./scripts/run_sql_tests.sh scratch_db_name
# WARNING: drops and recreates the named database. Never point this at a real/Supabase database.
set -euo pipefail
DB="${1:?scratch database name}"
PSQL="${PSQL:-psql}"
cd "$(dirname "$0")/.."
$PSQL -q -c "drop database if exists \"$DB\"" -c "create database \"$DB\""
for f in scripts/local_supabase_shim.sql supabase/migrations/*.sql supabase/seed.sql; do
  echo "applying $f"; $PSQL -q -v ON_ERROR_STOP=1 -d "$DB" -f "$f"
done
$PSQL -q -t -A -d "$DB" -f supabase/tests/behavior_test.sql | tail -1
