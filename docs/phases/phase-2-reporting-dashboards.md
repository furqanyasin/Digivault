# Phase 2 — Reporting & Agency Dashboards

**Status:** 🟢 Backend done — 2.1, 2.3, 2.4, 2.5 complete; 2.2 + Health Center UI are frontend (deferred).
**Blocks launch:** Reporting is a stated launch requirement; dashboards are high-value but can trail.

## Progress summary
- ✅ **2.1 Health Center** — `build_health_snapshot()` + derived security score; `GET websites/<id>/health/`.
- ⬜ **2.2 Renewal Center** — frontend screen (backend renewal data exists via 1.5 + 2.5).
- ✅ **2.3 Reporting** — `reports` app, PDF/CSV, generate + download + monthly task (commit `c358eb1`).
- ✅ **2.4 Performance trends** — `weekly_trend()` + `detect_regression()`/`alert_on_regression()`; `GET websites/<id>/performance/trends/`; regression fires in-app Notification from run-view + task.
- ✅ **2.5 Client enrichment** — `assigned_to`, `monthly_revenue`, `support_tier`, `contract_renewal_date` + `assigned_websites_count`; migration `clients/0003`.

**Tests:** `test_health_center.py` (3), `test_trends.py` (5), `clients/test_enrichment.py` (1), `reports/test_reports.py` (7). Touched suites green (39).

Surface the data you already collect into the views agencies actually use daily.

---

## 2.1 — Website Health Center ⬜

> Mostly a **frontend aggregation** — the data already exists (health_score, monitors, domain/SSL, vulnerabilities, performance).

### Tasks
- [ ] Backend aggregate endpoint `GET /api/v1/websites/<id>/health/` returning: uptime, security score, performance summary, domain status, SSL status, script monitoring summary, overall health score (0–100).
- [ ] A reusable **Security Score** computed from vulnerabilities + SSL + script risk + PHP errors.
- [ ] Frontend Health Center view assembling the above into one screen.

### Files
- `apps/websites/views.py` (aggregate), possibly `apps/site_health/services.py` (security score)
- `frontend/src/app/(dashboard)/websites/[id]/` (health tab/screen)

### Acceptance
✅ One call returns the full health picture · score recomputes from live data · screen renders.

---

## 2.2 — Renewal Center (frontend) ⬜

> Backend data lands in Phase 1.5; this is the screen.

### Tasks
- [ ] Frontend Renewal Center listing domains, SSL, hosting, plugin licenses with Expiring Soon / Expired / Renewed buckets and urgency colors.

### Acceptance
✅ All renewal items in one prioritized view.

---

## 2.3 — Automated reporting system ✅

> New feature. The biggest net-new build in this phase. **Done** (ReportLab).

**Shipped:** new `apps/reports/` app — `Report` model (migration `0001`); `ReportBuilder` (gather + PDF via ReportLab + CSV); `generate_report` service (renders + persists to `media/reports/`); Celery `reports.generate_for_website` + `reports.generate_monthly` (beat: 1st of month 04:00 UTC); API `GET /reports/`, `POST /reports/generate/`, `GET /reports/<id>/download/`. Report covers overview, script changes, domain/SSL, performance, security (vulns + PHP errors), and derived recommendations. Tests: `tests/reports/test_reports.py` (7). `reportlab==4.2.5` added.

> Note: PDF *visual* layout needs human QA — automated tests assert valid PDF/CSV bytes + content, not appearance.

### Tasks
- [ ] `Report` model (team, website|null, period, generated_at, format, file ref, status).
- [ ] Report generation service assembling: website overview, uptime, security, performance, domain/SSL/expiry, script changes (added/removed), recommendations.
- [ ] **PDF** export (WeasyPrint or ReportLab) and **CSV** export.
- [ ] Celery task `reports.generate_monthly()` scheduled monthly; on-demand generate endpoint.
- [ ] Delivery: email the PDF / link via existing notification channels.

### Files
- `apps/reports/` (new app: models, services, tasks, views, urls, serializers)
- `requirements/base.txt` (PDF lib)
- `config/settings/base.py` (beat entry, INSTALLED_APPS)
- `frontend/src/app/(dashboard)/reports/`

### Test plan
- Generation produces a PDF + CSV with expected sections for a seeded website.
- Monthly task picks correct period boundaries.
- Empty-data website degrades gracefully.

### Acceptance
✅ Monthly + on-demand reports · PDF and CSV both valid · delivered via notifications.

---

## 2.4 — Performance trend analysis ⬜

### Tasks
- [ ] Weekly/monthly trend aggregation over `PerformanceReport`.
- [ ] Performance regression alerts (score drop beyond threshold fires a notification).

### Files
- `apps/performance/services.py`, `tasks.py`, `views.py`

### Acceptance
✅ Trends queryable · regression crossing threshold notifies.

---

## 2.5 — Client management enrichment ⬜

### Tasks
- [ ] Add to `Client`: assigned websites (link), assigned team members, monthly revenue, support tier, contract renewal date.
- [ ] Contract-renewal feeds the Renewal Center.

### Files
- `apps/clients/models.py`, `serializers.py`, `views.py`, migration

### Acceptance
✅ Client profile carries ops + commercial metadata · renewals surfaced.

---

## Phase 2 exit criteria

- [ ] Health Center endpoint + screen
- [ ] Renewal Center screen
- [ ] Automated PDF/CSV reporting (monthly + on-demand)
- [ ] Performance trends + regression alerts
- [ ] Enriched client profiles
