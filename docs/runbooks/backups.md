# Runbook — Backups, restore and the self-monitoring checks

Stacks Monitor runs on one VPS: Postgres, Redis, the api and every worker. Two things
follow from that, and this runbook covers both:

1. **The database has to leave the box every night** — `backup-db.sh`.
2. **Something outside the box has to notice when Stacks Monitor stops** — a
   monitoring product that fails silently is the worst failure it can have.

All commands run on the server as root, from the repo root
(`/home/stacksmonitor/app`). Below,
`C` means `docker compose -f docker-compose.production.cloudpanel.yml`.

---

## 1. One-time setup

### 1a. Keep the secrets that no backup contains

`.env.production` is **not** in git and **not** in the dump. Without it a
restored database cannot be used: the vault's passwords are Fernet ciphertext,
readable only with `VAULT_ENCRYPTION_KEY(S)`.

- Store the whole `.env.production` in the team password manager, and update it
  whenever it changes.
- After a vault key rotation (`key-rotation.md`), keep the **old** key too for
  as long as backups made under it are retained (56 days by default). A
  restored backup from before the rotation needs the key it was written with.

### 1b. Off-server storage (rclone)

Any rclone backend works. Backblaze B2 is the cheapest:

```bash
apt install -y rclone           # or: curl https://rclone.org/install.sh | bash
rclone config                   # new remote, name it "b2", type "b2", app key + id
rclone mkdir b2:stacksmonitor-backups
```

Use a B2 application key restricted to that one bucket. Then add to
`.env.production`:

```
BACKUP_RCLONE_REMOTE=b2:stacksmonitor-backups
BACKUP_PING_URL=https://hc-ping.com/<backup-check-uuid>
```

Optional, with defaults: `BACKUP_DIR=/var/backups/stacksmonitor`,
`BACKUP_KEEP_LOCAL_DAYS=7`, `BACKUP_KEEP_DAILY_DAYS=14`,
`BACKUP_KEEP_WEEKLY_DAYS=56`.

### 1c. Schedule it

`crontab -e` as root:

```
30 2 * * * cd /home/stacksmonitor/app && ./backup-db.sh >> /var/log/stacksmonitor-backup.log 2>&1
```

02:30 UTC, deliberately clear of the 03:00–03:45 Sunday purges. Run it once by
hand first and check the output ends in `Backup complete` with no `WARNING`.

### 1d. External checks (healthchecks.io, free tier)

Create **two** checks:

| Check | Period | Grace | Ping URL goes in |
|---|---|---|---|
| Stacks Monitor heartbeat | 5 min | 10 min | `HEARTBEAT_PING_URL` in `.env.production` |
| Stacks Monitor backup | 1 day | 2 hours | `BACKUP_PING_URL` in `.env.production` |

Route both to email and/or Slack, then `./deploy.sh` so the workers pick up
`HEARTBEAT_PING_URL`.

The heartbeat (`common.system_heartbeat`) pings only when beat is scheduling,
a worker is consuming, Postgres answers, **and** no active monitor is more than
`HEARTBEAT_MONITOR_GRACE_SECONDS` (5 min) past its due time. So a silent alert
from it means one of: beat stopped, the workers stopped, the database is
unreachable, or uptime checks have stopped running. The worker log names the
overdue monitor: `$C logs celery | grep system_heartbeat`.

The backup check pings only when a verified dump reached off-server storage. A
local-only run deliberately does not ping.

Finally, add an external HTTP monitor (UptimeRobot or Better Stack, free) on
`https://stacksmonitor.com/api/ready/`. That covers the case none of the
above can report: the whole server being down.

### 1e. After the first deploy of this change

Celery no longer stores task results. Free the memory the old ones hold:

```bash
$C exec redis redis-cli -n 3 flushdb      # db 3 is the result backend, and only that
$C exec redis redis-cli info memory | grep used_memory_human
```

---

## 2. Restore drill (quarterly, non-destructive)

A backup nobody has restored is a hope, not a backup. This restores into a
throwaway container and never touches production:

```bash
LATEST=$(ls -t /var/backups/stacksmonitor/stacksmonitor-*.dump | head -1)
# or from the remote: rclone copy b2:stacksmonitor-backups/daily/<file> /tmp/

docker run -d --name dv-restore-test -e POSTGRES_PASSWORD=drill postgres:16-alpine
sleep 5
docker exec dv-restore-test createdb -U postgres stacksmonitor
docker exec -i dv-restore-test pg_restore -U postgres -d stacksmonitor --no-owner < "$LATEST"
docker exec dv-restore-test psql -U postgres -d stacksmonitor \
  -c "select count(*) as credentials from credentials_credential;" \
  -c "select count(*) as websites from websites_website;" \
  -c "select max(captured_at) as newest_snapshot from scripts_scriptsnapshot;"
docker rm -f dv-restore-test
```

Pass: the counts look like production, and the newest snapshot is from the
night of the backup. Note the date and the result in the team log.

---

## 3. Real restore

### Same server, database lost or corrupted

```bash
# Stop everything that writes, leave db running
$C stop api celery celery-monitors celery-slow celery-beat

$C exec -T db dropdb -U stacksmonitor stacksmonitor
$C exec -T db createdb -U stacksmonitor stacksmonitor
$C exec -T db pg_restore -U stacksmonitor -d stacksmonitor --no-owner < /var/backups/stacksmonitor/<file>.dump

./deploy.sh        # brings everything back up; migrate runs on start
```

### New server

1. Install Docker, clone the repo to the same path, check out `main`.
2. Restore `.env.production` from the password manager (1a).
3. `$C up -d db`, wait for it to report healthy.
4. Fetch the dump with `rclone copy` (configure rclone as in 1b), then run the
   `createdb` + `pg_restore` lines above.
5. `./deploy.sh`, then the frontend (pm2) as in `docs/deploy.md`.
6. Point DNS at the new IP, and update every client firewall allowlist
   (SiteGround tickets, Cloudflare rules) with it: the monitoring egress IP
   has changed. `GET /api/v1/monitors/blocked-summary/` lists who needs telling.

### What is not backed up, on purpose

- **Redis** — the task queue, sessions, throttle counters and outbound
  cooldowns. Losing them logs everyone out and drops queued work, and the
  schedule refills the queue.
- **`media_files`** — monthly report PDFs and heatmap backdrop screenshots.
  Reports can be regenerated and screenshots are recaptured nightly.
