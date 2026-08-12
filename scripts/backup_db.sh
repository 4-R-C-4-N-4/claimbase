#!/usr/bin/env bash
# backup_db.sh — labelled snapshot of the claimbase Postgres store.
#
# Follows the shape of guru/scripts/backup_db.sh: a timestamped, labelled snapshot
# beside a manifest, refusing to keep a dump that fails verification.
#
# Usage:
#   scripts/backup_db.sh                 # label defaults to "manual"
#   scripts/backup_db.sh pre-rebuild     # custom label
#
# Writes:
#   ~/claimbase-backups/claimbase-<ts>-<label>.sql.gz
#   ~/claimbase-backups/claimbase-<ts>-<label>.sql.gz.manifest.txt
#
# Why this exists: extracted claims were destroyed twice — once by an unscoped
# delete, once by TRUNCATE CASCADE reaching claims through a foreign key. Both were
# recoverable only by a three-hour GPU re-run. Events are cheap to rebuild; claims
# are not, and "derived data is rebuildable" is not the same as "free to lose".

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/.." && pwd)"

CONTAINER="${CLAIMBASE_DB_CONTAINER:-claimbase-db}"
DB="${CLAIMBASE_DB:-claimbase}"
USER_="${CLAIMBASE_DB_USER:-claimbase}"

LABEL="${1:-manual}"
LABEL="$(echo "$LABEL" | tr -c '[:alnum:]-' '-' | sed 's/--*/-/g; s/^-//; s/-$//')"
[ -n "$LABEL" ] || { echo "label cannot be empty after sanitization" >&2; exit 1; }

docker inspect "$CONTAINER" >/dev/null 2>&1 || {
    echo "container not found: $CONTAINER" >&2; exit 1; }

OUT_DIR="$HOME/claimbase-backups"
mkdir -p "$OUT_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="$OUT_DIR/claimbase-${TS}-${LABEL}.sql.gz"

echo "  dumping $DB from $CONTAINER ..."
docker exec "$CONTAINER" pg_dump -U "$USER_" -d "$DB" --no-owner | gzip -9 > "$SNAP"

# A dump that cannot be read back is not a backup. Verify before reporting success,
# so a silent failure never masquerades as protection.
if ! gzip -t "$SNAP" 2>/dev/null; then
    echo "  FAILED: snapshot is not a valid gzip stream; removing" >&2
    rm -f "$SNAP"; exit 1
fi
LINES="$(zcat "$SNAP" | grep -c '^COPY ' || true)"
if [ "${LINES:-0}" -lt 5 ]; then
    echo "  FAILED: dump contains $LINES COPY blocks, expected the full schema; removing" >&2
    rm -f "$SNAP"; exit 1
fi

{
    echo "created:    $TS"
    echo "label:      $LABEL"
    echo "database:   $DB @ $CONTAINER"
    echo "size:       $(du -h "$SNAP" | cut -f1)"
    echo "copy blocks:$LINES"
    echo
    echo "row counts at snapshot time:"
    docker exec "$CONTAINER" psql -U "$USER_" -d "$DB" -t -A -F'  ' -c "
      select 'events', count(*) from events
      union all select 'claims', count(*) from claims
      union all select 'claims (extracted)', count(*) from claims where meta ? 'extractor_version'
      union all select 'entities', count(*) from entities
      union all select 'edges', count(*) from edges;"
    echo
    echo "restore with:"
    echo "  zcat $SNAP | docker exec -i $CONTAINER psql -U $USER_ -d $DB"
} > "$SNAP.manifest.txt"

echo "  ok: $SNAP"
sed -n '6,12p' "$SNAP.manifest.txt"
