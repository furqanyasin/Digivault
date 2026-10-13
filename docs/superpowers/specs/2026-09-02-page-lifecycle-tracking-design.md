# Page Lifecycle Tracking — Design

**Date:** 2026-09-02
**Status:** Approved design, pending implementation plan
**Branch target:** feature branch off `feat/wp-activity-log-phase-0`

## Problem

A page was created on digilatics.com and deleted roughly two minutes later. The
Change Log shows exactly one row for it:

```
Info   Page Discovered   —   New page found: https://digilatics.com/test...   —   2 Sept 2026
```

Two failures in that row:

1. It does not say what the page *was* — the description is a bare URL, cut off
   at `.../test...` by a 200px truncating cell.
2. It does not say what *happened* to the page. The deletion produced no row at
   all, and never will.

## Why the deletion is currently invisible

The discovery row exists only because a human loaded the page while it existed.
The snippet posted `window.location.href` (`apps/scripts/snippet.js:306`), that
URL had never appeared in a `ScriptSnapshot` before, and
`apps/scripts/tasks.py:329` raised `PAGE_DISCOVERED`.

The deletion generated no pageview, so nothing reported it. Digivault has one
public egress IP and no crawler, and the ingest payload carries no notion of a
page's HTTP status — only `page_url` (`apps/scripts/serializers.py:177`).
`SiteEvent.EventType` has no counterpart to `page_discovered`; the comment at
`apps/site_health/models.py:44` says so deliberately.

Two mechanisms were rejected before this design:

- **WordPress hooks.** `wp_sso_snippet.py:797` already hooks
  `transition_post_status` and would catch this in real time *with the actor's
  name*. Ruled out: clients paste the JS snippet only, no PHP.
- **Sitemap diffing.** `apps/site_health/tasks.py:308` already persists up to
  1000 sitemap URLs per SEO scan, so diffing consecutive scans would be free.
  Ruled out: SEO scans run every 7 days by default, so a page that lives two
  minutes never appears in any sitemap fetch.

What remains, and what this design builds: the JS snippet reports enough page
context to recognise a dead page, and a tightly bounded server-side
confirmation resolves pages no visitor returns to.

`/s.js` is served by us under `Cache-Control: max-age=300`, so snippet changes
reach every client site within five minutes with **no re-paste** — unlike the
PHP snippet, where re-paste is the whole cost centre.

## Architecture

### 1. `SitePage` — a durable page record

There is no page entity today. Pages are `DISTINCT page_url` over
`ScriptSnapshot`, and snapshots are purged at 90 days, so the existing discovery
guard re-announces any page quiet for 90 days as brand new. A lifecycle needs a
row that outlives snapshot retention.

New model in `apps/site_health/models.py` (same app as `SiteEvent`, `SeoReport`
and `FileManifest`; migration `site_health/0012`):

| Field | Purpose |
|---|---|
| `website` | FK, `related_name="pages"` |
| `url` | normalised absolute URL, unique per website |
| `title` | last `document.title` seen |
| `wp_ref` | WordPress post id, from the `page-id-N` / `postid-N` body class |
| `status` | `live` / `removed` |
| `first_seen_at`, `last_seen_at` | any observation, browser or server |
| `last_checked_at` | last server-side confirmation attempt |
| `removed_at`, `removed_reason` | `not_found` / `gone` / `redirected` |

Unique constraint on `(website, url)`. Index on `(website, status,
last_seen_at)` for candidate selection.

### 2. Snippet reports page context

Three optional fields added to `IngestPayloadSerializer`, all with defaults so a
cached old snippet keeps validating and the backend ships first:

- `page_title` — `document.title`, capped at 300 chars.
- `page_status` — `"ok"` or `"404"`.
- `wp_ref` — post id parsed from the body class.

A `page_kind` field (`page` / `single` / `archive`) was considered and cut as
YAGNI — nothing in this design branches on it. The body-class parsing that
yields `wp_ref` makes adding it later a one-line change.

404 detection, in order, most reliable first:

1. `document.body.classList.contains('error404')` — WordPress core `body_class()`.
2. `document.querySelector('.error404, .error-404, .not-found, #error-404')`.
3. `/^\s*(404|page not found|not found)\b/i` against `document.title` **and**
   no `page-id-N` / `postid-N` class present. The extra condition matters: a
   real article titled "404 Ways To…" carries a post id, a 404 template does
   not.

Snippet version bumps to `1.13`. The snippet re-fires many times per page load,
so every post for one page carries identical fields — idempotent by design.

### 3. Transition planner — pure, no DB

New module `apps/site_health/pages.py`, the `DiffEngine` analogue for pages:

```
plan_observation(existing: PageState | None, observed: Observation) -> list[Transition]
normalize_page_url(url: str) -> str
```

`normalize_page_url` strips the fragment and query, lowercases scheme and host,
drops a leading `www.`, and enforces a trailing slash — so a trailing-slash
difference cannot masquerade as a redirect.

Rules, given an observation of `(url, title, wp_ref, status)`:

**`status == "404"`**

- No `SitePage` for that URL → **ignore completely.** No page, no event, no
  snapshot. Otherwise a visitor mistyping a URL "discovers" a page that never
  existed, and 404 spam inflates storage.
- Page is `live` → `PAGE_REMOVED`, status becomes `removed`.
- Page is already `removed` → no event, no state change. The removal is already
  recorded and a browser observation is not a confirmation attempt, so
  `last_checked_at` is untouched.

**`status == "ok"`**

- No page at this URL, but `wp_ref` matches a `live` page at a *different* URL
  → `PAGE_URL_CHANGED`. Update the URL in place, keep `first_seen_at`. This is
  the page-level version of the `url_changed` problem CLAUDE.md documents for
  scripts: without it a slug edit reads as a delete plus a create. If more than
  one live page carries the same `wp_ref` — possible only from bad historical
  data — the most recently seen one wins and the rest are left alone.
- No page and no `wp_ref` match → `PAGE_DISCOVERED`, create the row. Still
  suppressed on a website's very first ingest, when every page is new by
  definition — the existing rule at `apps/scripts/tasks.py:329` is preserved.
  **Suppression applies to the event only: the `SitePage` row is always
  created.** Skipping the row would leave a site's original pages permanently
  untracked and so never eligible for removal detection.
- Page is `removed` → `PAGE_RESTORED`, status back to `live`.
- Page is `live` → no event. Bump `last_seen_at`, refresh `title` / `wp_ref`.

A 404 observation also **skips script upsert, form recording and snapshot
creation entirely**. A 404 page's scripts are the theme's, and feeding them into
that URL's diff window is the same class of mistake as the snapshot-to-snapshot
diffing CLAUDE.md warns about.

### 4. Confirmation sweep

New task `site_health.confirm_missing_pages`, hourly. Resolves pages no visitor
returns to — the case that motivated this work.

Candidate selection, `status="live"` only, restricted to sites that pass the
same active/paused gate `websites.run_due_passive_scans` already applies — a
cancelled or paused client must not keep receiving requests. Two tiers:

- **New and gone quiet** — `first_seen_at` within 7 days and `last_seen_at`
  older than `PAGE_CONFIRM_NEW_AFTER` (default 2 hours). This is the test-page
  case; it resolves within hours.
- **Established and long quiet** — `last_seen_at` older than
  `PAGE_CONFIRM_STALE_AFTER` (default 30 days), rotating
  oldest-`last_checked_at` first. Catches real removals on low-traffic sites
  without hammering anyone.

Capped at `PAGE_CONFIRM_MAX_PER_SITE` (10) per site per run and
`PAGE_CONFIRM_MAX_PER_RUN` (200) overall, mirroring
`MONITOR_MAX_CHECKS_PER_TICK`. Without the caps a 500-page site becomes a
crawler by volume even though every URL is already known.

Each candidate gets **one** `outbound.fetch(url, method="HEAD")`, inheriting the
per-host token bucket keyed on registrable domain, the `Retry-After`/429
cooldowns, the WAF fingerprinting and the SSRF guard re-applied on every
redirect hop.

Interpreting the result — only positive evidence concludes anything:

| Outcome | Conclusion |
|---|---|
| `404` | `PAGE_REMOVED`, reason `not_found` |
| `410` | `PAGE_REMOVED`, reason `gone` |
| `200`, `final_url` normalises equal | live; treat as an `ok` observation |
| `200`, `final_url` normalises different | `PAGE_REMOVED`, reason `redirected`, `details.redirected_to` — "that page now redirects to /services/" is exactly what an agency needs |
| `result.blocked_by` non-empty | nothing learned. Mirrors `blocked` being neither up nor down for monitors |
| 5xx, 429, other | nothing learned |
| `HostCoolingDownError`, `RateLimitedError`, `BlockedURLError` | nothing learned, no retry this run |

Every branch writes `last_checked_at`, so a permanently unresolvable page
rotates to the back of the queue instead of being retried forever.

An unattributable 403 stays inconclusive here rather than becoming a removal —
the inverse of the monitor rule, because for a page the harmful error is
declaring a live page dead.

### 5. Events must not use summary dedupe

`_record_site_event` (`apps/scripts/tasks.py:492`) dedupes on
`(website, event_type, summary)`. Page lifecycle events **must not** go through
it. A page removed, restored, then removed again would have its second removal
silently swallowed — the same trap CLAUDE.md records for file integrity, where
events dedupe on `(walk_id, path)` and never on the summary alone.

The state machine is already the dedupe: a `live -> removed` transition can
happen only once before a restore. So page events are created unconditionally
from transitions.

New event types, all category `DISCOVERY` so they land under the existing
Change Log chip:

| Event type | Severity | Summary |
|---|---|---|
| `page_discovered` (existing) | info | `New page found: "Test Page" — /test-page/` |
| `page_removed` | warning | `Page removed: "Test Page" (/test-page/) — now returns 404` |
| `page_restored` | info | `Page is back: "Test Page" (/test-page/)` |
| `page_url_changed` | info | `Page URL changed: "Test Page" — /old/ -> /new/` |

`page_removed` is `warning`, not `info`: a deliberate delete is routine, but an
unexpected 404 on a page that was live is the kind of thing an agency must act
on, and severity is what makes it visible in a long log.

**No alert rule fires on any of these.** Change Log only. WordPress alerting is
deliberately narrow (`wp_alerts.py`) and routine page edits do not belong in an
inbox. Recorded here as a decision, not an omission.

### 6. Backfill migration

`site_health/0013`, a data migration seeding `SitePage` from:

- `DISTINCT page_url` over the last 90 days of `ScriptSnapshot`, and
- `details.page_url` on every existing `page_discovered` `SiteEvent`, which
  outlive snapshot retention.

`status="live"`, `first_seen_at` from the earliest evidence, `last_seen_at` from
the latest. **This is mandatory.** Without it every existing page on every
monitored site looks brand new on deploy and the Change Log floods with
`PAGE_DISCOVERED` — the failure `scripts/0029` had to repair for the analogous
script sweep.

### 7. Frontend

- Stop truncating the Description cell at
  `frontend/src/app/(dashboard)/websites/[id]/page.tsx:711` — allow wrapping and
  widen the column. This alone fixes the cut-off URL.
- Relabel the chip at `frontend/src/components/change-log-filters.tsx:29` from
  "New pages" to "Pages", since the category now carries four event types.
- No `SiteEvent` TypeScript change needed: `event_type` is a plain `string` and
  `event_type.replace(/_/g, " ")` already renders "page removed" correctly. The
  frontend deploys separately, so it must render new event types without a
  deploy — it does.

A dedicated Pages tab listing the inventory is **out of scope**; the model makes
it possible later.

### 8. Settings

`config/settings/base.py`, env-overridable: `PAGE_CONFIRM_NEW_AFTER` (2h),
`PAGE_CONFIRM_STALE_AFTER` (30d), `PAGE_CONFIRM_MAX_PER_SITE` (10),
`PAGE_CONFIRM_MAX_PER_RUN` (200), plus the hourly `confirm-missing-pages` entry
in `CELERY_BEAT_SCHEDULE`.

## Testing

Pure, no DB:

- `plan_observation` — table-driven over every state/observation pair above.
- `normalize_page_url` — trailing slash, `www.`, query, fragment, case.
- Result interpretation — the outcome table, including
  redirect-vs-trailing-slash.

Ingest (Celery eager, so `/api/ingest/` runs the pipeline inline):

- 404 for an unknown URL creates no page, no event, no snapshot.
- 404 for a known live page emits exactly one `page_removed`.
- `ok` after a removal emits `page_restored`.
- Same `wp_ref` at a new URL emits `page_url_changed`, **not** discovered plus
  removed.
- **Regression guard:** a payload with none of the new fields behaves exactly as
  today. This is the old cached snippet, and it will be most of the traffic for
  the first five minutes and any client with an aggressive CDN for longer.

Sweep:

- Candidate selection honours both tiers and both caps.
- `blocked_by`, 5xx and the three pre-network exceptions conclude nothing but
  still write `last_checked_at`.
- Redirect to a different path becomes `page_removed` with `redirected_to`.

Migration:

- Backfill seeds from both snapshots and historical events, and a subsequent
  ingest of an existing page raises no `page_discovered`.

`tests/conftest.py` — the `no_network_in_tests` autouse fixture must be extended
to patch the new confirmation fetch. It currently patches the uptime, domain,
performance and SEO checks; without the new one every ingest test that trips the
sweep starts making real requests.

Run with `pytest --create-db`, since this adds models and migrations.

## Consequences

- A page that lived two minutes and was never revisited is reported removed
  within roughly `PAGE_CONFIRM_NEW_AFTER` plus one sweep tick — hours, not
  instantly. Nothing outside the site can do better without a site-side hook.
- Removal detection is now the only part of script/page detection that makes
  requests the site did not ask for. It is bounded to already-known URLs, capped
  per site and per run, and rides the existing per-host budget — but it is a
  real departure from "passive and traffic-driven", and CLAUDE.md must say so.
- A page behind auth, or one that 403s to our UA, is never confirmed removed. It
  sits `live` with a stale `last_seen_at` and rotates through the sweep. That is
  the correct failure direction.
- `wp_ref` is WordPress-specific. On a non-WordPress site renames degrade to
  removed-plus-discovered, which is honest rather than wrong.
