#!/usr/bin/env bash
# Production deploy — run on the CloudPanel server from the repo root.
# Always uses the production compose file; plain `docker compose up` runs
# DEVELOPMENT settings (DEBUG=True, wrong ALLOWED_HOSTS) and must not be
# used on the server.
set -euo pipefail

COMPOSE_FILE=docker-compose.production.cloudpanel.yml

if [ ! -f .env.production ]; then
  echo "ERROR: .env.production is missing — create it before deploying." >&2
  echo "It needs everything from .env plus:" >&2
  echo "  ALLOWED_HOSTS=stacksmonitor.com" >&2
  echo "  CORS_ALLOWED_ORIGINS=https://stacksmonitor.com" >&2
  echo "  SNIPPET_CDN_URL=https://stacksmonitor.com/api" >&2
  echo "  DB_PASSWORD=<postgres password>" >&2
  exit 1
fi

# The deploy runs as the user that owns .git and .env.production (root on the
# CloudPanel box). Run as anyone else and `-f` above passes while every read
# fails, which used to surface as "EMAIL_URL is missing" — a real config file
# misreported as a broken one.
if [ ! -r .env.production ]; then
  echo "ERROR: .env.production exists but is not readable by $(id -un)." >&2
  echo "Re-run ./deploy.sh as the user that owns it (root)." >&2
  exit 1
fi

# Email pre-flight: without a real SMTP EMAIL_URL, onboarding and password-reset
# emails are silently discarded (and the API now refuses to boot without one).
EMAIL_LINE=$(grep -E '^EMAIL_URL=' .env.production || true)
if [ -z "$EMAIL_LINE" ] || echo "$EMAIL_LINE" | grep -qE 'consolemail|REPLACE_'; then
  echo "ERROR: EMAIL_URL in .env.production is missing or still a placeholder." >&2
  echo "Set it to the Brevo SMTP relay (see .env.production.example):" >&2
  echo "  EMAIL_URL=smtp+tls://LOGIN%40smtp-brevo.com:SMTP_KEY@smtp-relay.brevo.com:587" >&2
  echo "Also set DEFAULT_FROM_EMAIL to a sender on a Brevo-authenticated domain." >&2
  exit 1
fi

echo "==> Pulling latest main"
# frontend/package-lock.json is generated. A stray `npm install` on the server
# rewrites it, and the next pull then aborts on "local changes would be
# overwritten". It is canonical in git and `npm ci` below reinstalls from the
# pulled copy, so a local edit to it is never worth keeping.
if ! git diff --quiet -- frontend/package-lock.json; then
  echo "    frontend/package-lock.json was modified locally — restoring it from git."
  git checkout -- frontend/package-lock.json
fi

# Anything else dirty is not ours to discard. Fail loudly instead of guessing.
if ! git diff --quiet; then
  echo "ERROR: the working tree has local changes that would block the pull:" >&2
  git diff --name-only >&2
  echo "Commit, stash or revert them, then re-run ./deploy.sh." >&2
  exit 1
fi

git pull origin main

echo "==> Rebuilding backend (production settings)"
# Heatmap backdrop screenshots need a headless Chromium in the image (~400MB,
# shared by api/celery/celery-beat). On by default in production; opt out with
# WITH_CHROMIUM=0. Compose reads
# WITH_CHROMIUM from this shell or `.env` — NOT from .env.production, which is
# env_file and only reaches the container at runtime. Reported either way:
# rebuilding and still seeing "Screenshot capture is not enabled" with no
# explanation is what sends people looking for a bug that isn't there.
if [ -z "${WITH_CHROMIUM:-}" ] && [ -f .env ]; then
  # Mirror compose's precedence (shell first, then .env), or this line reports
  # one thing while the build does another.
  WITH_CHROMIUM=$(grep -E '^WITH_CHROMIUM=' .env | tail -n 1 | cut -d= -f2- | tr -d '"'"'"'\r ' || true)
fi
if [ "${WITH_CHROMIUM:-1}" = "1" ]; then
  echo "    Chromium: ON — heatmap screenshots enabled (first build pulls ~400MB)"
else
  echo "    Chromium: off — heatmap screenshots disabled (WITH_CHROMIUM=$WITH_CHROMIUM)."
  echo "    To enable: remove WITH_CHROMIUM from .env, or run WITH_CHROMIUM=1 ./deploy.sh"
fi
# Every Celery service is named here on purpose. Work is routed to three queues
# (ingest / monitors / slow — see CELERY_TASK_ROUTES), and a queue whose worker
# was never started does not run slowly, it never runs at all: uptime checks
# would simply stop with nothing in any log to say so. If you add a queue, add
# its worker here in the same commit. The same goes for api-ingest: it serves
# the snippet and ingest endpoints once nginx routes them to :8001, and a
# route to a container that was never started answers 502 to every client site.
docker compose -f "$COMPOSE_FILE" up -d --build \
  api api-ingest celery celery-monitors celery-slow celery-beat

echo "==> Building frontend"
cd frontend
# Install before building: the script used to go straight to `npm run build`, so
# a commit that added a dependency broke the deploy with "Module not found"
# (heatmap.js was the first). `npm ci` installs exactly what the lockfile pins
# and, unlike `npm install`, never rewrites it — which is what kept dirtying the
# tree and aborting the pull above.
npm ci
npm run build
pm2 restart stacksmonitor-frontend
cd ..

echo "==> Verifying snippet endpoint"
# Read the whole body before testing it. `curl | grep -q` under pipefail is a
# race: grep quits at the marker (~15KB into a ~50KB file), curl's next write
# hits a closed pipe (exit 23), and a healthy endpoint is reported broken.
# Retried because the api container may still be migrating or binding.
snippet_ok=0
for attempt in 1 2 3 4 5 6; do
  body=$(curl -sf --max-time 10 https://stacksmonitor.com/api/s.js || true)
  if grep -q snippet_version <<<"$body"; then
    snippet_ok=1
    break
  fi
  sleep 5
done
if [ "$snippet_ok" = "1" ]; then
  echo "OK: /api/s.js serves the tracking snippet."
else
  echo "WARNING: /api/s.js did not return the snippet after 30s — check ALLOWED_HOSTS and nginx." >&2
fi

echo "==> Verifying ingest worker pool"
# `up -d` does not wait for api-ingest to become healthy. Checked directly on
# its port, so it is verified even before nginx routes anything to it.
ingest_ok=0
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if curl -sf --max-time 5 http://127.0.0.1:8001/api/ready/ > /dev/null; then
    ingest_ok=1
    break
  fi
  sleep 5
done
if [ "$ingest_ok" = "1" ]; then
  echo "OK: api-ingest is ready on 127.0.0.1:8001."
else
  echo "WARNING: api-ingest is not answering on 127.0.0.1:8001 after 60s." >&2
  echo "If nginx routes the ingest paths there, client sites are getting 502s:" >&2
  echo "  docker compose -f $COMPOSE_FILE logs --tail 50 api-ingest" >&2
fi

echo "==> Done. Hard-refresh the browser to avoid stale JS bundles."
