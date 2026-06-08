# Phase 4 — Scale, Observability & Monetization

**Status:** ⬜ Not started
**Blocks launch:** No — for growth beyond the internal launch.

---

## 4.1 — Database scale ⬜

### Tasks
- [ ] Table partitioning for high-volume tables (`MonitorCheck`, `ScriptSnapshot`, `Notification`) — e.g. monthly range partitions.
- [ ] Archive tables for aged-out data before purge (cold storage).
- [ ] Verify indexes match real query patterns (uptime windows, change feeds, audit search).
- [ ] Consider TimescaleDB / continuous aggregates for monitor metrics if Postgres-native rollups strain.

### Acceptance
✅ Hot tables partitioned · archive path before delete · query plans verified.

---

## 4.2 — External-call resilience ⬜

### Tasks
- [ ] Caching for WHOIS / PageSpeed / WPScan responses (TTL appropriate per source).
- [ ] Circuit breakers + exponential backoff on external APIs.
- [ ] Per-provider rate-limit budgets so one slow API can't starve workers.

### Files
- `apps/domains/services.py`, `apps/performance/services.py`, `apps/site_health/tasks.py`

### Acceptance
✅ External outages degrade gracefully · no worker starvation · cache hit-rate measured.

---

## 4.3 — Full observability stack ⬜

### Tasks
- [ ] Prometheus metrics (API latency, Celery queue depth, task duration, DB pool).
- [ ] Grafana dashboards.
- [ ] Flower for Celery (if not added in Phase 0).
- [ ] Alerting on worker health, queue backlog, error rate.

### Acceptance
✅ Dashboards live · alerts on infra degradation.

---

## 4.4 — WebSocket header auth + real-time dashboard ⬜

### Tasks
- [ ] Move WS auth from query-string JWT to subprotocol/header (avoid token leakage in logs/proxies).
- [ ] Wire the dashboard to subscribe to the existing `ws/alerts/` channel for live notification updates.

### Files
- `apps/alerts/consumers.py`
- `frontend` dashboard real-time hook

### Acceptance
✅ No token in WS URL · dashboard updates in real time.

---

## 4.5 — Extension hardening ⬜

### Tasks
- [ ] Reduce host permissions from `<all_urls>` where possible (optional per-site activation).
- [ ] Strict postMessage origin validation review.
- [ ] Improve token handling (rotation, scope).

### Files
- `extension/manifest.json`, `extension/content.js`, `extension/background.js`

### Acceptance
✅ Minimal permission surface · origins validated · tokens scoped.

---

## 4.6 — Monetization (plan limits + billing) ⬜

### Tasks
- [ ] Plan-based quotas (websites, monitors, check frequency, team seats) enforced via permissions/middleware.
- [ ] Stripe billing + usage metering + upgrade/downgrade flows.
- [ ] Plan gating in UI.

### Files
- `apps/accounts/` (plan enforcement), new `apps/billing/`
- `frontend` billing/upgrade screens

### Acceptance
✅ Quotas enforced per plan · Stripe checkout + webhooks · metering accurate.

---

## Phase 4 exit criteria

- [ ] Partitioning + archive
- [ ] External-call resilience
- [ ] Prometheus/Grafana/Flower
- [ ] WS header auth + live dashboard
- [ ] Extension hardened
- [ ] Plan limits + Stripe billing
