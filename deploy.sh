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
  echo "  ALLOWED_HOSTS=digivault.digilatics.co" >&2
  echo "  CORS_ALLOWED_ORIGINS=https://digivault.digilatics.co" >&2
  echo "  SNIPPET_CDN_URL=https://digivault.digilatics.co/api" >&2
  echo "  DB_PASSWORD=<postgres password>" >&2
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
git pull origin main

echo "==> Rebuilding backend (production settings)"
docker compose -f "$COMPOSE_FILE" up -d --build api celery celery-beat

echo "==> Building frontend"
cd frontend
npm run build
pm2 restart digivault-frontend
cd ..

echo "==> Verifying snippet endpoint"
sleep 3
if curl -sf https://digivault.digilatics.co/api/s.js | grep -q snippet_version; then
  echo "OK: /api/s.js serves the tracking snippet."
else
  echo "WARNING: /api/s.js did not return the snippet — check ALLOWED_HOSTS and nginx." >&2
fi

echo "==> Done. Hard-refresh the browser to avoid stale JS bundles."
