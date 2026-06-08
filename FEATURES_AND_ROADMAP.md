# Digivault — Features, Challenges & Improvement Plan

> Status snapshot as of 2026-06-08. A SaaS platform for web agencies to monitor third-party scripts, uptime, performance, security, domains, and credentials across client websites.

---

## 1. Architecture Overview

| Component | Stack | Location |
|-----------|-------|----------|
| **Backend** | Django 5.1 + DRF + Celery + PostgreSQL + Redis + Channels (Daphne ASGI) | `/` |
| **Frontend** | Next.js 16 (App Router) + React 19 + TypeScript + Tailwind v4 | `frontend/` |
| **Extension** | Chrome Manifest V3 (content script + service worker + popup) | `extension/` |

**Cross-cutting backend conventions:**
- Multi-tenancy: every resource scoped to a `Team`; `TeamScopedMixin` + `.for_team()` enforce isolation.
- Response envelope: `{ data, errors, meta }` via `EnvelopeJSONRenderer`.
- `BaseModel`: UUID PK, `created_at` (indexed), `updated_at`, default `-created_at` ordering.
- Auth: JWT (15-min access, 7-day refresh) + TOTP 2FA + RBAC (Owner/Manager/Developer/Viewer).

---

## 2. Current Features

### 2.1 Accounts, Teams & Auth
- Email-based custom `User` with `active_team`, timezone, profile photo.
- **Teams** with plans (Starter / Agency / Agency Pro / Enterprise), slug, owner; auto owner membership.
- **Team memberships** with roles: Owner, Manager, Developer, Viewer.
- **Two-Factor Auth (TOTP)** — setup/confirm/verify/disable, QR codes (pyotp + qrcode), backup codes + regeneration.
- **Team invitations** — email + token-gated acceptance, expiry.
- **Admin-gated password reset** — request → approve/reject → confirm flow.
- **Active-team switching.**
- Team settings incl. encrypted **ClickUp API token** + test endpoint.

### 2.2 Websites
- Register client sites (WordPress, Webflow, Wix, Framer, Shopify, etc.).
- 43-char `site_id` token for snippet auth; regeneration.
- **Computed health score (0–100)** from script changes, domain/SSL expiry, vulnerabilities.
- Status: Active / Inactive / Warning / Critical; tags & notes.
- Platform-specific snippet HTML + install instructions.
- Async `run_initial_checks` (uptime + domain + performance) on creation.

### 2.3 Script Detection & Diffing
- JS snippet (`/api/s.js`) → `POST /api/ingest/` with per-page script payloads.
- **`ScriptSnapshot`** raw payloads (90-day retention, weekly purge).
- **`DiffEngine`** (pure fn) detects: added, removed, moved, URL-changed, inline-changed, plugin-changed.
- **`ScriptClassifier`** — provider + category (analytics, advertising, tag mgmt, session recording, CRM, payment, SEO, security, social…).
- Script metadata: location (head/body/footer/dynamic), scope (global/page-specific/one-time), async/defer/inline + SHA-256 inline hash, WP plugin/post enrichment, `seen_on_pages`.
- **Review workflow**: Pending / Approved / Blocked / Ignored.
- Severity classification (Critical/High/Medium/Low) + acknowledgement.
- **Noise filtering**: self-hosted scripts, utility CDNs (jQuery/Bootstrap), webpack chunks.
- **Detected forms** capture (fields, action, method) per page.

### 2.4 Credentials Vault
- **Fernet AES-256** encryption; key only in `VAULT_ENCRYPTION_KEY` env var.
- Encrypted username/password/notes; SHA-256 `username_hash` for fast lookup.
- Credential types (WordPress, cPanel, GoDaddy…), login URL, website link.
- **RBAC**: Owners/Managers full access; Developers view-only unless shared; creators full access to own.
- **`CredentialShare`** — fine-grained per-user grants.
- **`CredentialAccessLog`** — immutable audit of reveal/copy/edit (INSERT-only policy).
- **Reveal endpoint** decrypts + logs; key rotation support.
- Extension autofill via hashed-domain lookup.

### 2.5 Domain & SSL Intelligence
- `DomainInfo` (1:1 website): WHOIS (registrar, registration/expiry, nameservers, privacy, auto-renew), hosting (provider, IP, location, Cloudflare detection), SSL (issuer, expiry, auto-renew).
- Computed days-until-expiry for domain & SSL.
- `DomainAlert` thresholds (90/60/30/14/7 days); dedupe; daily `check_all_domains` (06:00 UTC).
- `DomainIntelligenceService` — stateless, never raises (python-whois + socket/ssl stdlib).

### 2.6 Uptime Monitoring
- `Monitor` types: HTTP, Ping, Port, SSL.
- HTTP options: expected status, method, headers, body, keyword match.
- Intervals 30s–1h, timeout, retry count before alerting.
- States: Up / Down / Degraded / Paused / Pending; consecutive-failure tracking.
- Cached uptime: 24h / 7d / 30d.
- `MonitorCheck` history (response time, status code, error).
- **Notification channels** (Email, ClickUp) + per-monitor rules (down/recovery/degraded).
- Celery: `run_due_checks` every 30s → `check_single_monitor`; dedupe + recovery alerts.
- Pause/resume/check-now endpoints.

### 2.7 Alerts & Notifications
- `AlertRule` — per-team or per-website (website rules shadow global); min severity, change-type filter.
- Channels: **Email, Slack, In-App** (SMS scaffolded, not implemented).
- Delivery modes: Immediate / Hourly digest / Daily digest.
- `Notification` records with delivery status, read state, digest grouping.
- Delivery backends (`delivery.py`): Email (Django mail), Slack (webhook), In-App (WebSocket); retry 3× w/ 30s backoff.
- **Real-time WebSocket** push via Django Channels (`ws/alerts/?token=<JWT>`), team-scoped Redis groups.

### 2.8 Performance Monitoring
- `PerformanceReport` — Google PageSpeed Insights (mobile/desktop): score + Core Web Vitals (FCP, LCP, CLS, TBT, TTFB, SI, TTI, INP) with ratings.
- `CruxReport` — Chrome UX Report real-user p75 metrics + good/needs-improvement/poor distributions.

### 2.9 Site Health & Security
- `PhpError` ingestion (fatal/error/warning/notice…), file/line/URL.
- `SiteEvent` audit (plugin/theme/core changes, deployments).
- **WPScan vulnerability scanning** (`run_security_scan`): plugin detection → WPScan API or heuristic patterns → CVE + CVSS→severity mapping → `VulnerabilityReport`.
- `SiteScanState` tracks scan status, WP version, detected plugins.

### 2.10 Status Pages
- `StatusPage` (public, slug-based, robots toggle) aggregating monitors.
- Computed overall status (operational/degraded/outage).
- 90-day uptime bars; public auto-refreshing page (`/status/[slug]`, refresh 10s).

### 2.11 Clients (CRM-lite)
- `Client` metadata: hosting platform/renewal, migration status, PPC/maintenance flags, notes.
- **ClickUp task sync** (create/update), import, search, bulk sync-all, activate/deactivate (soft delete).

### 2.12 Audit & Compliance
- `ActivityLog` — immutable, indexed by team/actor; covers auth, credentials, websites, team membership, settings.
- 90-day retention (weekly purge); free-form JSON metadata; INSERT-only policy.

### 2.13 Chat
- Dashboard chatbot (`/api/v1/chat/`) — intent matching via `intents.py` (command-driven, not LLM-backed).

### 2.14 Chrome Extension
- Credential **autofill** (shadow-DOM UI, single-click for sole match, dropdown for multiple, SPA-friendly events).
- **Credential capture** (LastPass-style save prompt, SPA login detection).
- Third-party **script ingestion** from pages.
- **Tab badge** showing script count (green=known, orange=unknown).
- **Web↔Extension SSO** handoff (token sync both directions).
- **Password generator** (length/charset, strength meter).
- **Alerts tab** (per-site script categorization).
- Configurable server URL (self-hosted/staging); auto token refresh on 401.

### 2.15 Scheduled Jobs (Celery Beat)
| Job | Schedule |
|-----|----------|
| Monitor checks | every 30s |
| Domain checks | daily 06:00 UTC |
| Snapshot purge | Sun 03:00 UTC |
| Audit log purge | Sun 03:30 UTC |
| Hourly digest | hourly :00 |
| Daily digest | daily 08:00 UTC |

---

## 3. Challenges & Gaps

### 3.1 Functional gaps
- **SMS delivery scaffolded but not implemented** — `AlertRule` exposes SMS channel + `sms_phone_number` with no backend.
- **Chat is rule-based, not AI** — `intents.py` is command matching; product likely expects LLM-grade answers.
- **Notification channels limited to Email + ClickUp** for monitors, while alerts support Slack/In-App — inconsistent channel coverage across subsystems.
- **No billing / subscription enforcement** — plans exist on `Team` but no plan-based limits, metering, or payment integration.
- **No CSV/PDF export or reporting** — agencies typically need client-facing reports; none present.
- **No bulk operations** on websites/scripts/monitors beyond clients import/sync.

### 3.2 Data & retention
- **Unbounded growth**: `MonitorCheck`, `PerformanceReport`, `PhpError`, `VulnerabilityReport`, `Notification` have no purge tasks — only snapshots & audit logs are purged. With 30s monitor checks this is the biggest scaling risk.
- **No aggregation/rollup** of monitor checks — uptime recalculated from raw rows; will degrade as history grows.

### 3.3 Performance & scaling
- **30s monitor fan-out** (`run_due_checks` → per-monitor task) — needs review for N+1 task explosion and worker saturation at scale.
- **Health score recalculation** triggered across multiple subsystems — verify it isn't recomputed synchronously on hot paths.
- **WHOIS/PageSpeed/WPScan** are external, rate-limited, slow APIs — need caching, backoff, and circuit-breaking review.
- **Per-request `serverUrl` fetch** in extension background worker — minor overhead, repeated.

### 3.4 Security posture
- **Single Fernet key, no documented rotation runbook** — `rotate_key` exists but no operational process / multi-key (MultiFernet) fallback during rotation.
- **Extension host permission `<all_urls>`** + content script on every page — broad attack surface; review postMessage origin validation rigor.
- **Public ingest endpoints** (`/api/ingest/`, `/api/php-errors/`) authenticated only by `site_id` — spoofing/abuse risk; verify rate limits & validation.
- **INSERT-only DB policies** for audit/access logs are documented but require DB-level enforcement (GRANTs) that may not be applied in all environments.

### 3.5 Reliability & observability
- **No mention of error tracking** (Sentry) or structured logging/metrics for Celery tasks.
- **External-call failures** in stateless services swallow errors — silent degradation risk without alerting on the alerting system itself (dead-man's switch).
- **WebSocket auth via query-string JWT** — token can leak in logs/proxies; consider subprotocol header auth.

### 3.6 Testing & quality
- Test coverage scope unknown beyond the recent credentials sharing work — need a coverage baseline across all 14 apps, especially diff engine, classifier, checker, and delivery backends.
- **Next.js 16 + React 19** are bleeding-edge — guard against API drift (project already flags reading `next/dist/docs`).

### 3.7 Frontend
- Auth token stored in **localStorage via Zustand persist** *and* httpOnly cookies — dual source of truth; XSS exposure of tokens in localStorage.
- No visible **optimistic UI / real-time wiring** to the existing WebSocket channel from the dashboard (alerts exist server-side; confirm client subscribes).

---

## 4. Improvement Plan

Phased so you can launch incrementally. Each phase is independently shippable.

### Phase 0 — Pre-launch hardening (must-do before launch)
1. **Add retention/rollup tasks** for `MonitorCheck`, `PerformanceReport`, `PhpError`, `Notification` (purge + daily uptime rollup table). *Biggest scaling risk.*
2. **Security review of public ingest endpoints** — validate `site_id`, tighten rate limits, add payload size caps.
3. **Fernet key rotation runbook** + switch to `MultiFernet` for zero-downtime rotation.
4. **Move JWT out of localStorage** — rely on httpOnly cookies only; audit XSS surface.
5. **Add Sentry + structured Celery logging** and a **dead-man's-switch** monitor on the alerting pipeline.
6. **Coverage baseline**: run `pytest --cov=apps`, set a floor, fill gaps in diff engine / classifier / checker / delivery.

### Phase 1 — Close functional gaps
1. **Implement SMS delivery** (Twilio/Vonage backend in `delivery.py`) or remove the option from UI/model to avoid dead settings.
2. **Unify notification channels** — let monitors use Slack/In-App and alerts use ClickUp; single channel abstraction.
3. **Client-facing reports** — scheduled PDF/CSV summaries (uptime, performance, security) per client.
4. **Bulk operations** on websites/monitors.

### Phase 2 — Monetization & limits
1. **Plan-based quotas** (websites, monitors, check frequency, team seats) enforced via middleware/permissions.
2. **Stripe billing** + usage metering + upgrade/downgrade flows.

### Phase 3 — Differentiation
1. **LLM-backed chat** (Claude) over the team's own data (scripts, monitors, vulnerabilities) — replace `intents.py` rule matching.
2. **Smarter classification** — ML/LLM-assisted provider/category detection beyond URL patterns.
3. **Anomaly detection** on script changes & performance regressions.

### Phase 4 — Scale & polish
1. **Monitor-check aggregation** (TimescaleDB / continuous aggregates or pre-rolled tables).
2. **Circuit breakers + caching** for WHOIS/PageSpeed/WPScan.
3. **WebSocket header-auth** + dashboard real-time wiring.
4. **Extension**: reduce permission surface, optional per-site activation.

---

## 5. Launch Checklist

- [ ] Phase 0 hardening complete (retention, ingest security, key rotation, token storage, observability, coverage floor).
- [ ] All env vars documented & set in production (`DJANGO_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `VAULT_ENCRYPTION_KEY`, optional `WPSCAN_API_KEY`, PageSpeed key, `EMAIL_URL`, `FRONTEND_URL`).
- [ ] Celery worker + beat + Daphne running and monitored (per deployment: docker backend + pm2 frontend on :3006).
- [ ] DB-level INSERT-only GRANTs applied for audit & credential access logs.
- [ ] Backups for PostgreSQL (incl. encrypted credential blobs) + key escrow for `VAULT_ENCRYPTION_KEY`.
- [ ] Rate limits verified on all public endpoints.
- [ ] Status page + monitors live for Digivault's own infrastructure.
- [ ] Decide SMS: implement or hide.
- [ ] Smoke test full flow: register → snippet install → ingest → change detected → alert delivered (email/Slack/in-app).

---

*Generated from a full read of `apps/` (14 Django apps), `frontend/src/app/` (App Router), and `extension/`. See `CLAUDE.md` for architecture conventions.*
