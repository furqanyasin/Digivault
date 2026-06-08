# Phase 3 — New Monitoring Subsystems

**Status:** ⬜ Not started
**Blocks launch:** No — these are genuinely new product areas. Build after existing features are verified.

These are the only items in the roadmap with **no existing models/tasks** — true greenfield.

---

## 3.1 — Backup monitoring ⬜

### Tasks
- [ ] `BackupStatus` model (website, provider, last_backup_at, status, size, recovery_verified_at).
- [ ] Ingest path or provider API integrations (e.g. WP plugin webhook, hosting API) to report backup events.
- [ ] Celery check: flag websites with no backup in N days.
- [ ] Recovery verification tracking (manual or automated marker).
- [ ] Feeds Website Health Center + alerts.

### Files
- `apps/backups/` (new app)
- frontend backup tab on website detail

### Acceptance
✅ Backup freshness tracked · stale-backup alerts · status in health view.

---

## 3.2 — Screenshot monitoring ⬜

### Tasks
- [ ] Daily screenshot capture (headless Chromium / Playwright worker or external screenshot API).
- [ ] Store images (object storage / media) with per-website history.
- [ ] Visual diff to detect layout changes, white screens, missing pages.
- [ ] Alert on significant visual change.

### Files
- `apps/screenshots/` (new app: model, capture task, diff service)
- worker/infra for headless browser
- frontend screenshot history + diff viewer

### Notes
- Heaviest infra lift in the roadmap (headless browser fleet or paid API). Budget accordingly.

### Acceptance
✅ Daily screenshots stored · visual diffs computed · alerts on white-screen/layout break.

---

## 3.3 — Status page enhancements ✅ (backend)

**Shipped:** branding (`logo_url`, `brand_color` on StatusPage); `StatusPageIncident` model (investigating→resolved, auto `resolved_at`) + CRUD; `MaintenanceWindow` model (+ `is_active`) + CRUD; public page now returns branding + active/recent incidents + upcoming/active maintenance. Migration `status_pages/0002`. Tests: `test_incidents_maintenance.py` (5). Frontend rendering still pending.

---

## 3.3 — Status page enhancements (original plan) ⬜

### Tasks
- [ ] Branding (logo, colors) per status page.
- [ ] Custom domains (CNAME + cert handling).
- [ ] Incident reports (create/update/resolve, posted to public page).
- [ ] Scheduled maintenance windows (suppress alerts + show banner).

### Files
- `apps/status_pages/models.py`, `views.py`, `serializers.py`, migrations
- `frontend/src/app/status/[slug]/` + management screens

### Acceptance
✅ Branded pages · custom domains resolve · incidents + maintenance windows publish.

---

## 3.4 — LLM-backed chat ⬜

> Replace `apps/chat/intents.py` rule matching with Claude over the team's own data.

### Tasks
- [ ] Tool/function layer exposing read access to scripts, monitors, vulnerabilities, domains scoped to the team.
- [ ] Claude integration (latest model; see `claude-api` skill for model ids/params).
- [ ] Guardrails: team-scoped data only, no cross-tenant leakage, rate limiting.

### Files
- `apps/chat/` (services, client)
- `requirements/base.txt` (anthropic SDK)

### Acceptance
✅ Natural-language Q&A over team data · strictly tenant-scoped · rate-limited.

---

## Phase 3 exit criteria

- [ ] Backup monitoring live
- [ ] Screenshot monitoring live
- [ ] Status page branding/incidents/maintenance
- [ ] LLM chat (optional, differentiator)
