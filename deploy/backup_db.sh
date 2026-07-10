#!/usr/bin/env bash
# Pre-migration database backup (Phase-10 P0 safety rail).
#
# Run ON THE SERVER before any phase that ships a migration or mass repoint:
#   bash /home/ls_user/htdocs/72.62.81.34.nip.io/deploy/backup_db.sh [label]
#
# Writes a compressed custom-format dump to /root/db-backups/ (same place as the
# 2026-07 full-reset backup) and prunes dumps older than KEEP_DAYS.
#
# Restore (full):
#   sudo -u postgres pg_restore -d linksentinel --clean --if-exists <file>
# Restore (single table, e.g. link_types):
#   sudo -u postgres pg_restore -d linksentinel --clean --if-exists -t link_types <file>
set -euo pipefail

LABEL="${1:-manual}"
DIR=/root/db-backups
KEEP_DAYS=30
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${DIR}/linksentinel-${STAMP}-${LABEL}.dump"

mkdir -p "${DIR}"
sudo -u postgres pg_dump -d linksentinel -Fc -Z6 -f /tmp/ls-backup.dump
mv /tmp/ls-backup.dump "${OUT}"
chmod 600 "${OUT}"
find "${DIR}" -name 'linksentinel-*.dump' -mtime +${KEEP_DAYS} -delete

echo "backup written: ${OUT} ($(du -h "${OUT}" | cut -f1))"
