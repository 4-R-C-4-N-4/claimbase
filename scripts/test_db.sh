#!/usr/bin/env bash
# test_db.sh — a scratch Postgres for the DB-touching tests and for `replay`.
#
# The memory-layer tests write: they open PRs, supersede claims, run the writer.
# They must never do that to the live store, so they get their own container on
# their own port and skip themselves when it is not up. Nothing here touches
# claimbase-db.
#
# Usage:
#   scripts/test_db.sh up        # start (or reuse) the container, apply migrations
#   scripts/test_db.sh reset     # drop and recreate the database, re-apply
#   scripts/test_db.sh down      # remove the container
#
# Tests read CLAIMBASE_TEST_DSN (default below).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
NAME="${CLAIMBASE_TEST_CONTAINER:-claimbase-test}"
PORT="${CLAIMBASE_TEST_PORT:-5434}"
DB="${CLAIMBASE_TEST_DB:-claimbase_test}"

psql_() { docker exec -i "$NAME" psql -q -v ON_ERROR_STOP=1 -U claimbase "$@"; }

wait_ready() {
  for _ in $(seq 1 60); do
    docker exec "$NAME" pg_isready -q -U claimbase 2>/dev/null && return 0
    sleep 0.5
  done
  echo "test database did not become ready" >&2; exit 1
}

migrate() {
  # The read role is created by hand on a real store; a scratch one needs it
  # too, or the read-only guarantees cannot be tested.
  psql_ -d "$DB" <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claimbase_ro') THEN
    CREATE ROLE claimbase_ro LOGIN PASSWORD 'claimbase_ro';
  END IF;
END $$;
ALTER ROLE claimbase_ro SET default_transaction_read_only = on;
ALTER ROLE claimbase_ro SET statement_timeout = '10s';
SQL
  for f in "$ROOT"/migrations/*.sql; do
    psql_ -d "$DB" < "$f" >/dev/null
  done
  psql_ -d "$DB" -c "GRANT SELECT ON ALL TABLES IN SCHEMA public TO claimbase_ro" >/dev/null
  echo "ok: $DB migrated ($(ls "$ROOT"/migrations/*.sql | wc -l) files) on port $PORT"
}

case "${1:-up}" in
  up)
    if ! docker inspect "$NAME" >/dev/null 2>&1; then
      docker run -d --name "$NAME" \
        -e POSTGRES_USER=claimbase -e POSTGRES_PASSWORD=claimbase -e POSTGRES_DB="$DB" \
        -p "127.0.0.1:$PORT:5432" pgvector/pgvector:pg17 >/dev/null
    else
      docker start "$NAME" >/dev/null
    fi
    wait_ready
    # Idempotent: 001 has bare CREATE TABLEs, so only migrate an empty database.
    if [ "$(psql_ -d "$DB" -Atc "SELECT to_regclass('public.events') IS NOT NULL")" = "t" ]; then
      psql_ -d "$DB" < "$ROOT/migrations/008_memory.sql" >/dev/null
      echo "ok: $DB already migrated; 008 re-applied"
    else
      migrate
    fi
    ;;
  reset)
    wait_ready
    psql_ -d postgres -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" >/dev/null
    psql_ -d postgres -c "CREATE DATABASE $DB" >/dev/null
    migrate
    ;;
  down)
    docker rm -f "$NAME" >/dev/null && echo "removed $NAME"
    ;;
  *)
    echo "usage: $0 up|reset|down" >&2; exit 2 ;;
esac
