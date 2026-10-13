#!/usr/bin/env bash
# Nightly Postgres backup — run on the CloudPanel server from the repo root,
# by host cron (see docs/runbooks/backups.md for the crontab line and restore).
#
# Everything — Postgres, Redis, api, workers — lives on one VPS, so a dump that
# stays on that VPS does not survive the failure it exists for. The dump is only
# a backup once it is somewhere else: set BACKUP_RCLONE_REMOTE. Without it this
# still dumps locally, and says loudly that it is not enough.
#
# The vault's credentials are Fernet ciphertext inside this dump. It is useless
# without VAULT_ENCRYPTION_KEY(S) — which must therefore be kept, separately,
# for every key that was primary at any point in the retention window.
#
# Settings (environment, or a BACKUP_*= line in .env.production):
#   BACKUP_DIR              local directory              (/var/backups/stacksmonitor)
#   BACKUP_KEEP_LOCAL_DAYS  local retention              (7)
#   BACKUP_RCLONE_REMOTE    rclone target, e.g. b2:stacksmonitor-backups  (unset = local only)
#   BACKUP_KEEP_DAILY_DAYS  remote daily retention       (14)
#   BACKUP_KEEP_WEEKLY_DAYS remote weekly retention      (56)
#   BACKUP_PING_URL         healthchecks.io-style URL pinged on success, so a
#                           backup that silently stops running pages someone
set -euo pipefail

COMPOSE_FILE=docker-compose.production.cloudpanel.yml
C="docker compose -f $COMPOSE_FILE"

cd "$(dirname "$0")"

# Read one BACKUP_* key from the environment, falling back to .env.production.
# Grepped rather than sourced: .env.production is a compose env_file, not a
# shell script, and values in it are not shell-quoted.
setting() {
  local name=$1 default=$2 value
  value=${!name:-}
  if [ -z "$value" ] && [ -r .env.production ]; then
    value=$(grep -E "^${name}=" .env.production | tail -n1 | cut -d= -f2- || true)
  fi
  echo "${value:-$default}"
}

BACKUP_DIR=$(setting BACKUP_DIR /var/backups/stacksmonitor)
KEEP_LOCAL_DAYS=$(setting BACKUP_KEEP_LOCAL_DAYS 7)
REMOTE=$(setting BACKUP_RCLONE_REMOTE "")
KEEP_DAILY_DAYS=$(setting BACKUP_KEEP_DAILY_DAYS 14)
KEEP_WEEKLY_DAYS=$(setting BACKUP_KEEP_WEEKLY_DAYS 56)
PING_URL=$(setting BACKUP_PING_URL "")

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# One run at a time: a dump slow enough to overlap the next cron firing would
# otherwise be read half-written by the upload step.
exec 9>"$BACKUP_DIR/.lock"
if ! flock -n 9; then
  echo "backup-db: another backup is still running; skipping." >&2
  exit 1
fi

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FILE="$BACKUP_DIR/stacksmonitor-$STAMP.dump"
PARTIAL="$FILE.partial"
trap 'rm -f "$PARTIAL"' EXIT

echo "==> Dumping Postgres to $FILE"
# Custom format (-Fc): compressed, and pg_restore can restore single tables
# from it. `exec -T` because cron has no TTY. Written to .partial and renamed
# only once verified, so a crash never leaves a truncated file that looks good.
umask 077
$C exec -T db pg_dump -U stacksmonitor -Fc --no-owner stacksmonitor > "$PARTIAL"

# pg_restore --list reads the archive's table of contents end to end; a
# truncated or corrupt dump fails here instead of on the day it is needed.
if ! $C exec -T db pg_restore --list < "$PARTIAL" > /dev/null; then
  echo "backup-db: ERROR — dump failed verification, not keeping it." >&2
  exit 1
fi
mv "$PARTIAL" "$FILE"
echo "    $(du -h "$FILE" | cut -f1), verified"

if [ -n "$REMOTE" ]; then
  echo "==> Uploading to $REMOTE"
  rclone copy "$FILE" "$REMOTE/daily/"
  # Sundays also go to weekly/, which is kept longer.
  if [ "$(date -u +%u)" = "7" ]; then
    rclone copy "$FILE" "$REMOTE/weekly/"
  fi
  rclone delete --min-age "${KEEP_DAILY_DAYS}d" "$REMOTE/daily/"
  rclone delete --min-age "${KEEP_WEEKLY_DAYS}d" "$REMOTE/weekly/"
else
  echo "WARNING: BACKUP_RCLONE_REMOTE is not set — this backup exists only on" >&2
  echo "this server and will not survive losing it. See docs/runbooks/backups.md." >&2
fi

find "$BACKUP_DIR" -maxdepth 1 -name 'stacksmonitor-*.dump' -mtime "+$KEEP_LOCAL_DAYS" -delete

# Only a backup that reached off-server storage counts as a success worth
# reporting; a local-only run deliberately does not ping, so the external check
# keeps complaining until the remote is configured.
if [ -n "$PING_URL" ] && [ -n "$REMOTE" ]; then
  curl -fsS -m 10 --retry 3 "$PING_URL" > /dev/null || \
    echo "backup-db: ping to $PING_URL failed" >&2
fi

echo "==> Backup complete: $FILE"
