# Digivault — Upcoming Features Roadmap

Forward-looking backlog of features not yet built (or only partially built).
Derived from the 2026-06-17 codebase audit in [feature-plan-status.md](feature-plan-status.md). Items are
grouped by theme; effort is a rough estimate (S = small/self-contained,
M = medium, L = large/new subsystem).

**Legend:** `[ ]` not built · `[~]` partial (some of it exists).

---

## Near-term — high value, builds on existing infrastructure

These extend systems that already exist (`site_health`, `monitors`,
`credentials`, `reports`) and are good candidates to ship next.

- [ ] **Plugin / theme update-available checks** (S–M) — WP core update detection
      already works (`SiteScanState.wp_update_available`); extend the same pattern
      to plugins and themes via the WordPress.org API.
- [~] **Credential health: reused / shared-password detection** (S) — weak + old
      detection already exist; add reuse detection (compare password hashes within a team).
- [ ] **DNS & API monitor checks** (M) — add `dns` and `api` to `Monitor.MonitorType`
      and implement `check_dns` / `check_api` in `apps/monitors/checker.py`.
- [ ] **Maintenance-mode detection** (S) — flag 503 / known maintenance pages in HTTP checks.
- [ ] **Heartbeat / cron-job monitoring** (M) — inbound ping endpoint + "expected interval" alerting.
- [ ] **Broken-link detection** (M) — crawl the rotating SEO page set, report 4xx/5xx links.
- [~] **Form-failure alert delivery** (S) — failures are captured (`FormSubmissionError`);
      wire them into the notification channels.
- [~] **Report cadences + per-client white-label** (M) — monthly branded PDF/CSV exists;
      add weekly/SLA cadences and per-client logo/colors.

## Mid-term — new subsystems

- [ ] **Incident Management** (L) — auto incident creation from monitor/security events,
      severity levels, status workflow, timeline, postmortems.
- [ ] **Synthetic form testing** (L) — scheduled real submissions with email & CRM
      delivery verification.
- [ ] **Malware scanning** (M–L) — signature/heuristic scan of served assets.
- [ ] **Brute-force / login-attempt monitoring** (M) — ingest auth-failure signals + alerting.
- [ ] **Backup monitoring** (M) — verify backup freshness/health per site.
- [ ] **Maintenance windows** (S–M) — suppress alerts during scheduled windows.
- [ ] **Additional notification channels** (M) — SMS, WhatsApp, Telegram, Discord
      (Email / Slack / In-app / ClickUp already supported).
- [ ] **Server resource monitoring** (L) — CPU / RAM / disk / inode / bandwidth + hosting risk score.

## Larger / strategic

- [ ] **HTML / CSS / DOM / layout diffing** (L) — structural change detection beyond scripts/SEO.
- [ ] **Visual monitoring** (L) — screenshot capture, visual-regression detection,
      real-browser / JS-error monitoring.
- [ ] **Website dependency mapping** (L) — service dependency graph + impact analysis.
- [ ] **Traffic integrations** (L) — Google Analytics, Search Console, Ahrefs, SEMrush.
- [ ] **AI Operations** (M–L) — incident summaries, smart recommendations, predictive monitoring
      (chat assistant already exists).
- [ ] **Emergency / temporary credential access links** (M) — time-boxed, audited share links.
- [ ] **Premium-license expiry, abandoned-plugin detection, safe-update prediction** (M–L).

## Analytics & team features

- [ ] **Client risk score** + client analytics (avg health, downtime, response times).
- [ ] **Structured access-verification checklist** (hosting / registrar / WP / MFA).
- [ ] **Developer analytics** (deployments, incidents, response/fix times) + risky-developer detection.
- [ ] **Task assignment, incident chat, internal notes.**
- [ ] **Multi-region monitoring.**
- [ ] **Auto ticket / incident creation + auto escalation by severity.**

---

## Operational follow-ups (from feature-plan-status.md Part 3)

- [ ] Deploy Tier 3 commit `9df0387` to production.
- [ ] Reconcile health-score vs UI "pending" definition mismatch.
- [ ] Fix ~19 pre-existing test failures (legacy `resp.data["data"]` envelope pattern + one WebSocket loop issue).
