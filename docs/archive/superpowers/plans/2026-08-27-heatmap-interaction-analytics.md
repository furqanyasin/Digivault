# Heatmap Interaction Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real, in-product heatmap dashboard where an agency can see where its clients' visitors click, move, scroll and rage-click across a page — collected by the existing tracking snippet and aggregated into a percentage grid so the overlay lines up on any viewport.

**Architecture:** The tracking snippet bins every raw interaction (click, mouse move, scroll endpoint) into a 100x100 percentage grid (x = % of viewport width, y = % of full page height) and POSTs the aggregated cells to a public `POST /api/ingest/heatmap/` endpoint. A Celery task (`process_heatmap_payload`) sums those cells into two tables — `HeatmapActivity` (one row per cell) and `HeatmapPageStats` (one row per page+segment summary) — using a straight `count += N` accumulation so there is no per-event granularity. Versioned `GET /api/v1/heatmap/*` endpoints (team-scoped, segmented by device/visitor_type/source) feed a Next.js dashboard that renders a `heatmap.js` overlay on an iframed copy of the live page, plus a scroll-depth strip.

**Tech Stack:** Django 5.1, DRF, Celery, PostgreSQL, Django Channels (not used here), the existing tracking snippet (`apps/scripts/snippet.js` → `GET /api/s.js`), Next.js 16 frontend, `heatmap.js` for the overlay render.

**Spec:** This plan; the earlier scope-notes spec that introduced the section-gating lives at `docs/superpowers/specs/2026-08-07-heatmap-access-js-errors-client-websites-design.md`.

## Global Constraints

- Ingest lives under `/api/ingest/heatmap/` — the same **version-free** public prefix as script ingest, so production nginx (which only proxies `/api/ingest|...`) already forwards it and `PublicIngestCorsMiddleware` already allows it. Do not move it under `/api/v1/`.
- **All** request-facing reads go through `TeamScopedMixin` + `IsTeamMember`; both models expose `.for_team()` via `HeatmapQuerySet` (keyed on `website__team`). The snippet-facing write is unauthenticated (authorised by `site_id`), domain-bound (Origin/Referer host must match the registered `website.domain`), and throttled per-site (`HeatmapIngestThrottle`, 2000/day).
- No per-event data is ever stored. The snippet aggregates into cells first; the task only sums. This is what keeps the table small on a busy site.
- `visits` increments **only** on a `final` flush (page unload). Intermediate periodic flushes carry their cells and click totals but never inflate the pageview count.
- A page's cells and stats are bucketed by `device` / `visitor_type` / `source`. The frontend expresses "all" by omitting the param.
- `scroll_histogram` is `{ bucket: share_reached }` for buckets 5..100 step 5; the snippet's own histogram wins, else a synthetic linear-decay curve anchored on `max_scroll_percent`.
- The snippet must normalize positions as **page fractions** (y = document position / full page height), not screen pixels, so scrolling is already handled and the overlay lines up on any viewport.
- Tests: run `pytest tests/heatmap/ -q --create-db` after any model/migration change. DRF `response.data` in tests is the raw payload, not the envelope.

---

### Task 1: Aggregating data models + initial migration

Establishes the storage before anything can write to it.

**Files:**
- Create: `apps/heatmap/models.py`
- Create: `apps/heatmap/apps.py`, `apps/heatmap/__init__.py`
- Create: `apps/heatmap/migrations/0001_initial.py` (generated)
- Register: `apps.heatmap` in `INSTALLED_APPS` (`config/settings/base.py:53`)

**Status: DONE.** `HeatmapActivity` (unique on website/page_url/kind/device/visitor_type/source/x/y, cells with `count`, best-effort `element` descriptor, `first_seen_at`/`last_seen_at`) and `HeatmapPageStats` (unique on website/page_url/device/visitor_type/source; visits, total_clicks, max_scroll_percent, scroll_histogram). Migrations 0001–0004 applied. `apps.heatmap` is registered and committed.

- [x] Models written (`apps/heatmap/models.py`)
- [x] Migration generated and applied
- [x] App registered in `INSTALLED_APPS`
- [x] HeatmapQuerySet `.for_team()` isolation

---

### Task 2: Ingest serializer + endpoint

The snippet-facing write surface.

**Files:**
- Create: `apps/heatmap/serializers.py`
- Create: `apps/heatmap/views.py` (`HeatmapIngestView`, `HeatmapIngestThrottle`)
- Create: `apps/heatmap/urls.py` (`ingest_urlpatterns`)
- Modify: `config/urls.py` — mount `ingest_urlpatterns` at `/api/`

**Status: DONE.** Serializer bounds every cell (x/y 0–100, count ≥ 1, ≤ 100k, kind from `HeatmapActivity.Kind`), payload ≤ 512 KB (413 on overflow), and returns 202 while `process_heatmap_payload.delay()` runs. Domain-bound: a mismatched Origin/Referer host returns 403. Route mounted at `api/` together with the script ingest.

- [x] `HeatmapIngestSerializer` with cell/payload caps
- [x] `HeatmapIngestView` POST (202 / 404 / 400 / 403 / 413)
- [x] Per-site throttle
- [x] Domain/Origin check
- [x] Route mounted at `/api/ingest/heatmap/`

---

### Task 3: Celery aggregation task

**Files:**
- Create: `apps/heatmap/tasks.py`

**Status: DONE.** `process_heatmap_payload` runs in one transaction: get-or-create each cell then `count += N` via `F()` (never clobbering the count), preserve a non-blank `element`, upsert page stats with running totals, `visits += 1` only when `final`, and build the scroll histogram (snippet value wins, else synthetic). Silent guard on unknown `site_id`.

- [x] Cell accumulation (`F()` sum)
- [x] Element descriptor preserved (blank never wipes)
- [x] Page stats upsert + `final`-gated visits
- [x] Scroll histogram build (snippet-histogram → synthetic fallback)
- [x] Silent drop of unknown site_id

---

### Task 4: Versioned read endpoints

**Files:**
- Create: `apps/heatmap/views.py` (`HeatmapPageListView`, `HeatmapCellListView`, `HeatmapSiteSummaryView`)
- Modify: `apps/heatmap/urls.py` (`urlpatterns`)
- Modify: `config/urls.py` — mount at `/api/v1/`
- Create: `apps/heatmap/serializers.py` (`HeatmapPageSerializer`, `HeatmapCellSerializer`)

**Status: DONE.** `GET /api/v1/heatmap/pages/` (paginated, feeds page selector), `GET /api/v1/heatmap/activity/` (unpaged, bounded by the grid; `?kind=&device=&page_url=`), `GET /api/v1/heatmap/summary/` (one summary dict per device). All team-scoped via `TeamScopedMixin` + `IsTeamMember`; `apply_segment_filters` narrows by device/visitor_type/source. Mounted under `/api/v1/`.

- [x] Pages list (paginated, `StandardPagination`)
- [x] Activity cells (unpaged, ordered x/y, kind/device/page_url filters)
- [x] Site summary (per-device visit/click/max-scroll totals)
- [x] Team scoping + segment filters
- [x] Routes mounted at `/api/v1/heatmap/*`

---

### Task 5: Snippet collection

The client side that detects, bins and flushes interactions.

**Files:**
- Modify: `apps/scripts/snippet.js`

**Status: DONE** (in working tree, **NOT committed**). Adds a heatmap block that: derives `device`/`visitor_type`/`source`, normalizes pointer/scroll events to page-fraction percentages, bins into the 100x100 cell map, records a best-effort element descriptor for click/rage cells (tag selector or link text), detects rage-click bursts, and flushes aggregated cells to `/ingest/heatmap/` on a timer and on unload. The final unload flush sets `final: true`.

- [x] Device / visitor_type / source derived client-side
- [x] Click / move / scroll / rage handlers writing percentage cells
- [x] Element descriptors for click/rage cells
- [x] Scroll histogram build
- [x] Periodic + final (unload) flush to `/ingest/heatmap/`
- [ ] **NOT COMMITTED — part of the uncommitted heatmap bundle**

---

### Task 6: Backend tests

**Files:**
- Create: `tests/heatmap/test_heatmap.py`
- Create: `tests/heatmap/test_read_endpoints.py`

**Status: DONE — 30 tests pass** (`pytest tests/heatmap/ -q --create-db` → `30 passed`). Covers ingest validation (202/400/403/404, element forwarding, unknown kind), aggregation (accumulation, final-gated visits, mobile bucket separation, max-scroll keeping highest, invalid-cell skipping, rage accumulation, element preservation) and read endpoints (auth required, team scoping both directions, device/kind filters, summary math).

- [x] 30 passing tests (ingest + aggregation + read endpoints)

---

### Task 7: Frontend dashboard

**Files:**
- Modify: `frontend/src/app/(dashboard)/heatmap/page.tsx` (server component, loads websites)
- Create: `frontend/src/components/heatmap-client.tsx` (the interactive dashboard)
- Create: `frontend/src/app/api/heatmap/{pages,activity,summary}/route.ts` (SSR proxy routes that forward the access-token cookie)
- Create: `frontend/src/types/heatmap-js.d.ts` (typings for the untyped `heatmap.js`)
- Modify: `frontend/package.json` / `package-lock.json` (add `heatmap.js@^2.0.5`)

**Status: DONE** (in working tree, **NOT committed**). The page shells out to `HeatmapClient`, which offers a website + page + device + map-kind selector, a summary header (observations / clicks / max scroll), and renders onto an iframed live page:
- **Click / Move / Rage** → `heatmap.js` overlay normalized to percentage coords on a reference width; rage uses a red-dominant palette.
- **Scroll** → a vertical reach strip (green = reached by all → red = few) with a dashed max-scroll line.
- A "top hotspots" list attributes the strongest cells to their element descriptor.

- [x] Dashboard component with selectors + summary cards
- [x] Click / move / rage overlay via `heatmap.js`
- [x] Scroll-depth reach strip
- [x] SSR proxy routes (cookie → Bearer token)
- [x] `heatmap.js` dependency + TypeScript declarations
- [ ] **NOT COMMITTED — part of the uncommitted heatmap bundle**
- [ ] Verify `npm run lint` + `npm run build` (see Task 9)

---

### Task 8: Config wiring

- `config/urls.py` — mount both heatmap url sets (`M`, done)
- `config/settings/base.py` — `apps.heatmap` in `INSTALLED_APPS` (committed)

---

### Task 9: Verification and commit the bundle

The backend, snippet, and frontend are all **uncommitted** in the working tree together. This is the remaining work.

**Files (to stage as one heatmap feature commit):**
- `apps/heatmap/` (models, serializers, views, urls, tasks, migrations, apps)
- `tests/heatmap/`
- `apps/scripts/snippet.js`
- `config/urls.py`
- `frontend/src/app/(dashboard)/heatmap/page.tsx`
- `frontend/src/components/heatmap-client.tsx`
- `frontend/src/app/api/heatmap/`
- `frontend/src/types/heatmap-js.d.ts`
- `frontend/package.json`, `frontend/package-lock.json`

- [x] **Step 1: Full backend test run**
  Run: `pytest tests/heatmap/ -q --create-db`
  Expected: PASS (30) — **verified 2026-08-31: 30 passed**

- [x] **Step 2: Regression sweep**
  Run: `pytest tests/scripts/ tests/websites/ tests/site_health/ -q`
  Expected: PASS — especially the snippet-adjacent and ingest-adjacent suites. **Verified 2026-08-31: 664 passed.**

- [x] **Step 3: Frontend lint**
  Run: `cd frontend; npm run lint`
  Expected: clean. Watch for the dynamic `import("heatmap.js")` and the `wegman/motion` icon imports in `heatmap-client.tsx`.
  **Verified 2026-08-31: clean — exit 0, 0 errors, 0 warnings.** No heatmap findings. The run initially failed on 4 pre-existing
  `react-hooks/set-state-in-effect` errors plus 1 `@next/next/no-img-element` warning in files this feature never touched
  (`(dashboard)/logs/page.tsx`, `clients-client.tsx`, `reports-tab.tsx`, `theme-toggle.tsx`, `(auth)/2fa/setup/page.tsx`); these were
  fixed separately using the repo's existing microtask-deferral idiom (`renewals-client.tsx:297`) so the gate is green.

- [x] **Step 4: Frontend build**
  Run: `cd frontend; npm run build`
  Expected: succeeds. `heatmap.js` has no types — the local `.d.ts` must cover what `heatmap-client.tsx` uses (`create`, `setData`, `remove`).
  **Verified 2026-08-31: compiled successfully**; `/heatmap` plus `/api/heatmap/{activity,pages,summary}` all present in the route manifest.

- [x] **Step 5: Commit the heatmap bundle** (single logical feature)
  ```bash
  git add apps/heatmap/ tests/heatmap/ apps/scripts/snippet.js config/urls.py \
    "frontend/src/app/(dashboard)/heatmap/page.tsx" frontend/src/components/heatmap-client.tsx \
    frontend/src/app/api/heatmap/ frontend/src/types/heatmap-js.d.ts \
    frontend/package.json frontend/package-lock.json
  git commit -m "feat(heatmap): interaction analytics dashboard (click/move/scroll/rage)"
  ```

- [ ] **Step 6: Deploy note**
  The snippet must be re-copy-pasted into client sites for the collection to start (it ships inside `/api/s.js`), and nginx already forwards `/api/ingest/heatmap/`. Production needs a full `./deploy.sh` (new models/migrations must reach the `api` container).

---
