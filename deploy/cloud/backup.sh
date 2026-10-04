#!/usr/bin/env bash
# Nightly: dump the control DB + every tenant DB, encrypted, keep 30 days.
# cron:  15 2 * * *  /opt/fa/deploy/cloud/backup.sh >> /var/log/fa_backup.log 2>&1
# Restore one client:  gpg -d --passphrase-file backup.pass <dir>/fa_acme.dump.gpg | docker compose exec -T db pg_restore -U fa_app -d fa_acme --clean
set -euo pipefail
cd "$(dirname "$0")"
source .env
STAMP=$(date +%Y%m%d_%H%M)
OUT=./backups/$STAMP
mkdir -p "$OUT"
DBS=$(docker compose exec -T db psql -U "$POSTGRES_USER" -d fa_control -Atc \
      "SELECT datname FROM pg_database WHERE datname LIKE 'fa_%'")
for DB in $DBS; do
  docker compose exec -T db pg_dump -U "$POSTGRES_USER" -Fc "$DB" \
    | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-file ./backup.pass \
    > "$OUT/${DB}.dump.gpg"
done
find ./backups -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
# copy off the server (object storage in another region), e.g.:
# rclone copy "$OUT" remote:fa-backups/$STAMP
echo "backup ok: $OUT"
