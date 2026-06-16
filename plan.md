# Digivault — Feature Plan & Status

Status tracker for the Digivault WebOps platform. Audited against
`digivault_webops_platform_features_master_spec.md` plus the recent improvement
tiers. Last updated 2026-05-22.

**Legend:** `[x]` built · `[ ]` not built. Each module carries an overall
status: **Built**, **Partial**, or **Not built**.

**Summary:** of 22 feature modules — 6 built, 12 partial, 4 not started.

---

## Part 1 — Platform Module Status

### Dashboard — Built
- [x] Overview stat cards (sites, issues, pending changes, high-risk, monitors, down)
- [x] Per-site health score display
- [x] High-risk changes section
- [x] Domains / SSL / Uptime panel (Tier 3)
- [ ] Failed-forms / open-incidents / pending-tasks widgets (modules not built)

### Client Management — Partial
- [x] Client profiles — hosting platform, renewal date, access location, notes, PPC, migration status
- [x] ClickUp task sync
- [x] Search / quick lookup by name and URL
- [ ] Client risk score
- [ ] Client analytics (avg health, downtime, response times, monthly reports)
- [ ] Structured access-verification checklist (hosting / registrar / WP / MFA)

### Website Management — Built
- [x] Website overview page
- [x] Tabs: Overview, Scripts, Plugins, Forms, Access & Domain, Performance, Change Log, PHP Errors, Site Events, Security, Setup

### Website Change Intelligence — Partial
- [x] Script change detection — diff engine, provider/category classification, severity
- [x] Risk classification of script changes
- [x] Infrastructure signals — SSL issuer, nameservers, Cloudflare (via DomainInfo)
- [ ] SEO change detection (meta title/description, H1, canonical, robots.txt, sitemap, schema)
- [ ] HTML / CSS / DOM / layout diffing

### Monitoring System — Partial
- [x] HTTP, Ping, TCP port, SSL checks
- [x] Domain + SSL expiry monitoring
- [x] Uptime %, check history, response times
- [x] Retry logic + alert deduplication (Tier 1)
- [ ] DNS checks, API checks
- [ ] Multi-region monitoring
- [ ] Heartbeat / cron-job monitoring
- [ ] Maintenance-mode detection

### Incident Management — Not built
- [ ] Auto incident creation, severity levels, workflow, timeline, postmortems

### Team Management — Partial
- [x] Teams, memberships, role-based access, invitations
- [x] 2FA (Google Authenticator) + manager disable (Tier 1)
- [ ] Developer analytics (deployments, incidents, response/fix times)
- [ ] Risky-developer detection
- [ ] Task assignment, incident chat, internal notes

### Website Timeline — Built
- [x] SiteEvent log — plugin updates/installs/removals, theme & core changes, deployments ("Site Events" tab)

### Forms Monitoring — Partial
- [x] Form detection (DetectedForm) — "Forms" tab
- [ ] Synthetic form testing (daily submission, email & CRM delivery verification)
- [ ] Form-failure alerts

### WordPress Intelligence — Partial
- [x] Plugin detection + WP version (SiteScanState)
- [x] Vulnerability scanning via WPScan (plugin / theme / core, CVEs)
- [ ] Premium-license expiry, abandoned-plugin detection
- [ ] Safe-update prediction, theme intelligence

### Credentials Vault — Built
- [x] Encrypted vault — Fernet / AES-256, 16 credential types
- [x] Access auditing — CredentialAccessLog (viewed / copied / edited + IP)
- [ ] Credential health (weak / old / shared password detection)
- [ ] Emergency / temporary access links

### Hosting Intelligence — Partial
- [x] Hosting provider / IP / Cloudflare detection (DomainInfo)
- [x] Hosting renewal date (Client)
- [ ] Server resource monitoring (CPU / RAM / disk / inode / bandwidth)
- [ ] Server resource monitoring (CPU / RAM / disk / inode / bandwidth)
- [ ] Hosting risk score

### Security Operations (SOC Lite) — Partial
- [x] Vulnerability scanning + scan state, "Security" tab
- [ ] Malware scanning
- [ ] Security-header validation (CSP, HSTS, X-Frame-Options)
- [ ] Brute-force / login-attempt monitoring
- [ ] Backup monitoring

### SEO & Performance — Partial
- [x] Performance — PageSpeed reports
- [x] Core Web Vitals — Chrome UX Report (CrUX)
- [ ] SEO monitoring (index status, robots, sitemap, meta, broken links, schema)
- [ ] Traffic integrations (Google Analytics, Search Console, Ahrefs, SEMrush)

### Smart Notification System — Partial
- [x] Channels — Email, ClickUp
- [x] Per-monitor notification rules
- [x] Alert deduplication (Tier 1)
- [x] Channel test button (Tier 2)
- [x] Domain / SSL expiry alert delivery (Tier 3)
- [ ] Slack, SMS, WhatsApp, Telegram, Discord channels
- [ ] Maintenance windows (alert suppression)

### Client Reporting — Not built
- [ ] Automated weekly / monthly / SLA reports, white-label branding

### AI Operations — Partial
- [x] AI chat assistant (`/api/chat`)
- [ ] AI incident summaries
- [ ] Smart recommendations
- [ ] Predictive monitoring

### Visual Monitoring — Not built
- [ ] Screenshot capture, visual-regression detection, real-browser / JS-error monitoring

### Website Dependency Mapping — Not built
- [ ] Service dependency graph, impact analysis

### Public Status Pages — Built
- [x] StatusPage + monitors, public `/status/<slug>` pages

### Audit Logs — Built
- [x] ActivityLog across logins, credential access, config changes
- [x] Previous / new value metadata (Tier 1)

### Automation System — Partial
- [x] Scheduled health checks via Celery Beat (monitors 30s, domains daily, digests)
- [ ] Auto ticket / incident creation
- [ ] Auto escalation by severity

---

## Part 2 — Recent Improvement Tiers

### Tier 1 — Quick-Win Improvements (Deployed)
Spec: `docs/superpowers/specs/2026-05-21-tier1-improvements-design.md`

- [x] **Monitor retry logic + alert deduplication** — `consecutive_failures` / `is_alerting` fields, `retry_count` default 1 → 3, retry-before-alert, single recovery notification
- [x] **Audit log metadata** — `ActivityLog.metadata` JSON, `AuditService.log()` metadata arg, recorded for role change / member removal / team rename / credential update, UI change-detail line
- [x] **2FA manager disable UI** — `TeamMembershipSerializer.totp_enabled`, per-member disable button

### Tier 2 — Proactive Health & Alerts (Deployed, commit `1f00c30`)
Spec: `docs/superpowers/specs/2026-05-21-tier2-improvements-design.md`

- [x] **Website health score (0-100)** — `health_score` field, `recalculate_health_score()`, triggers on acknowledge / domain check / security scan, API + frontend
- [x] **Dashboard action center** — `expiring-domains` / `expiring-ssl` endpoints, "Needs Attention" section (reworked in Tier 3)
- [x] **Notification channel test button** — `POST /notification-channels/<pk>/test/`, proxy route, inline Test button

### Tier 3 — Dashboard Visibility & Alert Delivery (Code done, commit `9df0387` — NOT yet deployed)

- [x] **Always-visible Domains / SSL / Uptime panel** — replaces the conditional block; every site's domain + SSL days-to-expiry, color-coded
- [x] **Domain / SSL expiry alert delivery** — `apps/domains/notifications.py`, `check_domain` delivers unsent alerts (most-urgent threshold only), migration marks pre-existing alerts sent
- [ ] **Deploy commit `9df0387` to production** — `git pull` → `docker compose up --build` → `migrate` → frontend rebuild → `pm2 restart`

---

## Part 3 — Known Issues / Follow-ups

Not tier features — surfaced during the work above.

- [ ] **Health score vs UI "pending" mismatch** — the score counts a DB-level unacknowledged change the website detail page hides as auto-acknowledged "noise" (digilaticsvps shows `97` while the UI says "0 pending"). Align the two definitions.
- [ ] **~19 pre-existing test failures** — old tests use the wrong `resp.data["data"]` envelope pattern; one WebSocket event-loop issue. Pre-date all tier work; not regressions.
