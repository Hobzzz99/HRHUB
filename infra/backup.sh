#!/usr/bin/env bash
# Nightly Postgres dump. The candidate database is the only thing here that
# cannot be rebuilt: profiles cost scrape budget to collect, and the budget is
# 20 an hour on an account that has already been restricted twice.
#
# Install on the server:
#   sudo crontab -e
#   0 2 * * * cd /opt/talentfinder && ./infra/backup.sh >> /var/log/tf-backup.log 2>&1
#
# Restore:
#   gunzip -c backups/talentfinder-YYYY-MM-DD.sql.gz \
#     | docker compose -f docker-compose.prod.yml exec -T postgres \
#         psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

set -euo pipefail

cd "$(dirname "$0")/.."
set -a && source .env.prod && set +a

KEEP_DAYS=${BACKUP_KEEP_DAYS:-14}
DEST="backups"
STAMP="$(date +%F)"
FILE="${DEST}/talentfinder-${STAMP}.sql.gz"

mkdir -p "$DEST"

docker compose -f docker-compose.prod.yml exec -T postgres \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
    | gzip > "$FILE"

# A dump that silently produced nothing is worse than no dump, because it looks
# like a backup until the day it is needed.
if [ ! -s "$FILE" ]; then
    echo "FAILED: ${FILE} is empty" >&2
    rm -f "$FILE"
    exit 1
fi

echo "$(date -Is) wrote ${FILE} ($(du -h "$FILE" | cut -f1))"

find "$DEST" -name 'talentfinder-*.sql.gz' -mtime "+${KEEP_DAYS}" -delete

# Copy off this machine. A backup on the same disk as the database survives a
# mistake but not a dead server.
if [ -n "${BACKUP_REMOTE:-}" ]; then
    rsync -az "$FILE" "$BACKUP_REMOTE" \
        && echo "$(date -Is) copied to ${BACKUP_REMOTE}"
fi
