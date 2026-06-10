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
