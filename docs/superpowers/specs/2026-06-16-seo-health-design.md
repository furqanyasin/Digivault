# SEO Health (Robots + Sitemap + Index/noindex) — Design

**Date:** 2026-06-16
**Status:** Approved (design); pending implementation plan

## Problem

Digivault detects scripts/forms passively and monitors uptime, domain, SSL, and
security. It has **no** visibility into three SEO-critical signals that silently
break client sites:

- `robots.txt` missing or accidentally blocking the whole site.
- `sitemap.xml` missing or unreachable.
- Pages set to `noindex` (meta robots or `X-Robots-Tag`) — a common deploy
  accident that de-indexes a site.

The platform is **passive/traffic-driven with no crawler**, but the existing
"Scan" action already performs a **server-side homepage fetch**
([apps/websites/views.py](../../../apps/websites/views.py)) behind an SSRF guard
(`apps/common/ssrf.py`). This design extends that same server-side fetch
capability — it does **not** introduce a general crawler.

## Decisions (from brainstorming)

1. **Configurable cadence, per website.** A `seo_scan_interval_days` setting
   (Off / 3 / 7 / 14 / 30) chosen from the dashboard. The interval governs the
   **SEO check only**, not security/performance.
2. **Alert on regressions** — flip to noindex, robots starts blocking all,
   sitemap disappears.
3. **Index check covers homepage + up to N key pages** (N = 10) discovered from
   the sitemap.

## Triggers

A check (`run_seo_check(website)`) runs:

- **Manual:** `POST /api/v1/websites/<id>/seo/` (a "Re-check" button).
- **On the existing Scan:** folded into the `scan` action so one scan covers
  scripts + security + SEO.
- **Scheduled:** a daily Celery-beat task `run_due_seo_checks` enqueues
  `run_seo_check.delay` for every website where `seo_scan_interval_days` is set
  and `last_checked_at + interval` is due (or never checked).

## Checks (all fetches reuse the scan's SSRF guard + browser headers, short timeouts)

### Robots
Fetch `/robots.txt`. Record: `robots_status` ∈ {found, missing, error};
capture `Sitemap:` directive URLs; set `robots_blocks_all = True` when the
record for `User-agent: *` contains `Disallow: /` with no overriding `Allow`.

### Sitemap
Resolve sitemap URL from robots `Sitemap:` directives, else fallback
`/sitemap.xml`. Record: `sitemap_status` ∈ {found, missing, error}; `sitemap_url`;
`sitemap_url_count`. A `<sitemapindex>` is followed one level deep (bounded to
the first 10 child sitemaps) to total the `<url>` entries; counting is capped to
avoid unbounded work.

### Index / noindex
For the homepage **plus up to N = 10 URLs** taken from the sitemap (deduped,
same-origin only): read `<meta name="robots">` and the `X-Robots-Tag` response
header. A page is **not indexable** if either contains `noindex`. Store
`homepage_indexable` and `pages_checked = [{url, indexable, reason}]`;
`noindex_count` = number of checked pages that are noindex.

## Data model (`apps/site_health`)

`SeoReport` — one per website (OneToOne, mirroring `SiteScanState`):

| Field | Type | Notes |
|-------|------|-------|
| `website` | OneToOne(Website) | `related_name="seo_report"` |
| `last_checked_at` | DateTime null | |
| `check_status` | Char | never / running / done / failed |
| `error` | Text blank | |
| `robots_status` | Char | found / missing / error |
| `robots_blocks_all` | Bool | |
| `sitemap_status` | Char | found / missing / error |
| `sitemap_url` | Char blank | |
| `sitemap_url_count` | Int default 0 | |
| `homepage_indexable` | Bool null | null until first check |
| `pages_checked` | JSON list | `[{url, indexable, reason}]` |
| `noindex_count` | Int default 0 | |

`Website.seo_scan_interval_days` — `PositiveSmallIntegerField`, choices
`{0: Off, 3, 7, 14, 30}`, default `0`.

New `SiteEvent.EventType` choices for the regression log:
`SEO_NOINDEX_DETECTED`, `SEO_ROBOTS_BLOCK`, `SEO_SITEMAP_MISSING`.

## Alerting on regressions

`run_seo_check` reads the existing `SeoReport` (previous state) before writing
the new one and diffs:

- `homepage_indexable` True → False, **or** `noindex_count` rises from 0 → ≥1.
- `robots_blocks_all` False → True.
- `sitemap_status` found → missing.

On any transition: create a `SiteEvent` (severity `critical` for noindex/robots-
block, `warning` for sitemap) **and** send a notification through the same
delivery path domain-expiry alerts use (`apps/domains/notifications.py` pattern →
alerts app delivery). The **first-ever** check (no prior report, or
`homepage_indexable` was null) only sets the baseline — no alerts.

## Components / files

**Backend**
- `apps/site_health/seo_checker.py` — pure functions `check_robots`,
  `check_sitemap`, `page_indexability`, plus `run_seo_check(website)` orchestrator
  (Celery task) that fetches, computes, diffs, persists, and fires events/alerts.
- `apps/site_health/models.py` — add `SeoReport` (+ migration); add `SiteEvent`
  event-type choices (+ migration).
- `apps/websites/models.py` — add `seo_scan_interval_days` (+ migration).
- `apps/site_health/views.py` — `WebsiteSeoView`: GET report, POST re-check,
  PATCH interval; wire into `site_health` `website_urlpatterns` as `seo/`.
- `apps/websites/views.py` — call `run_seo_check.delay` from the `scan` action.
- `apps/site_health/tasks.py` — `run_due_seo_checks` beat task; schedule entry in
  `config/settings/base.py`.

**Frontend**
- `frontend/src/components/seo-tab.tsx` — status cards (robots / sitemap /
  indexability), per-page table, "last checked", interval dropdown (PATCH), and
  Re-check button (POST).
- Wire an "SEO" tab into `frontend/src/app/(dashboard)/websites/[id]/page.tsx`.
- Proxy route(s) under `frontend/src/app/api/websites/[id]/seo/`.

## Error handling

- Unreachable site, 404 robots, malformed sitemap XML, non-HTML page → recorded
  as `missing`/`error` on the report; the run never raises to the worker.
- `assert_public_url` rejects private/loopback targets (SSRF) before any fetch.
- Page fetches are bounded (N = 10), each with a short timeout; total work capped.

## Testing

- `check_robots`: present, missing (404), blocks-all (`Disallow: /`), with
  `Sitemap:` directive.
- `check_sitemap`: plain sitemap URL count, `<sitemapindex>` aggregation, missing.
- `page_indexability`: indexable, `<meta robots noindex>`, `X-Robots-Tag: noindex`.
- Regression diff: fires events only on transitions; baseline (first run) is silent.
- `run_due_seo_checks`: selects only websites with interval set and due; skips Off.
- `WebsiteSeoView`: GET returns report, PATCH updates interval, POST triggers a run.

## Out of scope (YAGNI)
- Per-page indexability beyond N = 10 / multi-level sitemap recursion beyond one.
- Including SEO status in the PDF report (easy follow-up).
- Team-level default interval (per-website is enough for now).
- Robots/sitemap *content diffing* beyond the three regression signals.
