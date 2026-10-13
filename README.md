# Stacks Monitor

Website operations for web agencies: third-party script monitoring, uptime,
performance, domain and SSL tracking, a shared credentials vault, WordPress
activity, and status pages, under one team account.

Live at [stacksmonitor.com](https://stacksmonitor.com).

## Stack

| Part | Tech | Folder |
|---|---|---|
| API and workers | Django 5, DRF, Celery, PostgreSQL, Redis | `apps/`, `config/` |
| Dashboard | Next.js | `frontend/` |
| Browser extension | Chrome MV3 | `extension/` |
| Tracking snippet | Plain JS, served at `/api/s.js` | `apps/scripts/snippet.js` |

## Local development

```bash
cp .env.example .env          # fill in the keys it asks for
docker compose up             # api, celery, celery-beat, db, redis
cd frontend && npm ci && npm run dev
```

Tests: `pytest` (backend), `npm run lint && npm run build` (frontend).

## Docs

- [Platform guide](docs/platform-guide.md)
- [User guide](docs/guide/README.md)
- [Deploy](docs/deploy.md) and [runbooks](docs/runbooks/)
- [Extension](docs/extension.md)
- [Specification](docs/srs.md)
