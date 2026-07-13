# Phase 1 — Data-Correctness Bugs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix script over-counting, duplicate form counting, per-page change-log spam, managed-vs-embedded form counts, and the Google Ads URL display.

**Architecture:** A new pure `apps/scripts/normalize.py` module provides `normalize_script_url` (strips volatile cache-buster query params) and `normalize_page_url` (strips query/hash/trailing-slash). Script identity moves from raw `src_url` to a new `normalized_url` column; DiffEngine keys on normalized URLs; ScriptChange creation dedupes against open changes so a site-wide script fires one event, not one per page. DetectedForm fingerprints exclude volatile (nonce/honeypot) field names and forms key on normalized page URLs. Data migrations merge existing duplicates.

**Tech Stack:** Django 5.1, DRF, pytest (`--create-db` after model changes), Next.js 16 frontend.

## Global Constraints

- Tests: `pytest --create-db` after any migration change; Celery eager in tests; `resp.data` is raw payload (no envelope).
- DiffEngine stays a pure function — no DB access.
- Frontend: read `frontend/node_modules/next/dist/docs/` conventions before editing; `npm run build` must pass.
- Commit per task on branch `phase-0-hardening` (current working branch).

---

### Task 1: URL normalization module

**Files:**
- Create: `apps/scripts/normalize.py`
- Test: `tests/scripts/test_normalize.py`

**Interfaces:**
- Produces: `normalize_script_url(url: str) -> str`, `normalize_page_url(url: str) -> str` — both pure, safe on garbage input (return input unchanged on parse failure).

- [ ] **Step 1: Write failing tests** — ver/nonce/cb params stripped; meaningful params (`id=AW-…`, `id=GTM-…`, `render=`) kept; param order stable; protocol-relative handled; page URL loses query+hash+trailing slash, host lowercased, `www.` stripped.
- [ ] **Step 2: Run** `pytest tests/scripts/test_normalize.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement:**

```python
"""URL normalization — stable identity for scripts and pages.

WordPress and page builders append volatile cache-buster query params
(?ver=6.4.2, ?nonce=..., ?cb=...) to script URLs. Diffing raw URLs mints a
"new" script on every plugin update. These helpers strip only the volatile
params so meaningful identifiers (?id=GTM-XXX, ?id=AW-XXX) survive.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_VOLATILE_PARAMS = frozenset({
    "ver", "version", "nonce", "cb", "cachebust", "cache", "bust",
    "rev", "build", "t", "ts", "time", "timestamp", "_", "rand", "random",
})
_HEXLIKE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)


def normalize_script_url(url: str) -> str:
    if not url:
        return url
    raw = "https:" + url if url.startswith("//") else url
    try:
        parts = urlsplit(raw)
    except ValueError:
        return url
    if not parts.netloc:
        return url
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _VOLATILE_PARAMS and not _HEXLIKE.match(v)
    ]
    kept.sort()
    return urlunsplit((
        parts.scheme.lower() or "https", parts.netloc.lower(),
        parts.path, urlencode(kept), "",
    ))


def normalize_page_url(url: str) -> str:
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.netloc:
        return url
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", host, path, "", ""))
```

- [ ] **Step 4:** `pytest tests/scripts/test_normalize.py -v` → PASS.
- [ ] **Step 5: Commit** `fix(scripts): add URL normalization for stable script/page identity`

### Task 2: DiffEngine keys on normalized URLs

**Files:**
- Modify: `apps/scripts/diff_engine.py:66-67` (map building)
- Test: `tests/scripts/test_diff_engine.py`

**Interfaces:**
- Consumes: `normalize_script_url` from Task 1.
- Produces: `DiffEngine.diff` unchanged signature; a `?ver=` bump yields `[]`; `ChangeResult.src_url` carries the **normalized** URL.

- [ ] **Step 1: Failing tests** — `?ver=1.0`→`?ver=2.0` produces no changes; `?id=GTM-A`→`?id=GTM-B` still produces URL_CHANGED; duplicate raw URLs differing only in volatile params collapse to one entry.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Key `prev_map`/`curr_map` with `normalize_script_url(s["src"])`; keep the dict value's raw data:

```python
prev_map = {normalize_script_url(s["src"]): s for s in previous if s.get("src")}
curr_map = {normalize_script_url(s["src"]): s for s in current if s.get("src")}
```

(remaining logic already operates on map keys — no other change).
- [ ] **Step 4:** Full `pytest tests/scripts/test_diff_engine.py -v` → PASS (fix any tests asserting raw-URL keys).
- [ ] **Step 5: Commit** `fix(scripts): diff on normalized URLs — ver bumps no longer fake add/remove`

### Task 3: Script.normalized_url column + duplicate-merge migration

**Files:**
- Modify: `apps/scripts/models.py` (field + unique_together)
- Create: migrations `0008_script_normalized_url` (schema), `0009_merge_duplicate_scripts` (data), `0010_script_unique_normalized` (constraint)
- Test: `tests/scripts/test_script_dedup.py`

**Interfaces:**
- Produces: `Script.normalized_url` (TextField, indexed); uniqueness = `(website, normalized_url)`; `src_url` keeps the most recent raw URL.

- [ ] **Step 1:** Add field `normalized_url = models.TextField(blank=True, default="", db_index=True)`; leave old unique_together until 0010.
- [ ] **Step 2:** `makemigrations` → 0008. Data migration 0009: for each Script set `normalized_url = normalize_script_url(src_url)`; group per (website_id, normalized_url); keeper = earliest `created_at`; union `seen_on_pages`; keeper takes any non-pending `review_status` (priority approved > blocked > ignored) and `is_active = any(dup.is_active)`; repoint `ScriptChange.script` FKs to keeper; delete dups. Migration 0010: `unique_together = [("website", "normalized_url")]` (replacing `("website", "src_url")`).
- [ ] **Step 3:** Test: create two Script rows differing only by `?ver=`, run merge helper (import from migration or duplicate logic in a shared function `apps/scripts/dedup.py` used by the migration), assert single survivor with unioned pages.
- [ ] **Step 4:** `pytest tests/scripts/ --create-db -v` → PASS.
- [ ] **Step 5: Commit** `fix(scripts): script identity on normalized_url + merge existing duplicates`

### Task 4: Ingest task — normalized upsert, change dedupe, page URL normalization

**Files:**
- Modify: `apps/scripts/tasks.py` (`process_ingest_payload`, `_upsert_script`, `_upsert_form` call site)
- Test: `tests/scripts/test_ingest_dedup.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: one ScriptChange per real event site-wide; snapshots/forms stored under normalized page URLs.

- [ ] **Step 1: Failing tests** (full pipeline via `POST /api/ingest/`, Celery eager):
  - same new script reported from two different pages → exactly 1 `added` ScriptChange;
  - second ingest with only `?ver=` changed → 0 new ScriptChange, still 1 Script row;
  - same page ingested as `/contact`, `/contact/`, `/contact?utm=x` → 1 DetectedForm.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement:
  - top of task: `page_url = normalize_page_url(payload["page_url"])`;
  - `_upsert_script`: `get_or_create(website=website, normalized_url=normalize_script_url(src), defaults={... "src_url": src ...})`; update path also refreshes `src_url=src`;
  - deactivation query: `exclude(normalized_url__in={normalize_script_url(u) for u in current_urls})`;
  - change→script lookup: `filter(website=website, normalized_url=change.src_url)` (diff emits normalized);
  - dedupe before `ScriptChange.objects.create`:

```python
dup_q = ScriptChange.objects.filter(
    website=website, change_type=change.change_type,
    acknowledged_at__isnull=True,
)
dup_q = dup_q.filter(script=script_obj) if script_obj else dup_q.filter(description=change.description)
if dup_q.exists():
    continue
```

- [ ] **Step 4:** `pytest tests/scripts/ --create-db -v` → PASS (update any tests relying on per-page duplicate changes).
- [ ] **Step 5: Commit** `fix(scripts): dedupe change events site-wide; normalize page URLs at ingest`

### Task 5: Form fingerprint hardening + duplicate-merge migration

**Files:**
- Modify: `apps/scripts/models.py` (`DetectedForm.compute_fingerprint`)
- Create: migration `0011_merge_duplicate_forms`
- Test: `tests/scripts/test_form_fingerprint.py`

**Interfaces:**
- Produces: fingerprint stable across nonce/honeypot rotation; existing DetectedForm rows merged on (website, normalized page_url, new fingerprint).

- [ ] **Step 1: Failing test** — two payloads of the same form whose only difference is a rotating `_wpnonce`-style hidden field / hex-named honeypot produce equal fingerprints; genuinely different forms still differ.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** In `compute_fingerprint`, filter field names:

```python
_VOLATILE_FIELD = re.compile(
    r"(nonce|honeypot|^hp-|^_wpcf7|^g-recaptcha|^h-captcha|^ct_|^ak_)", re.IGNORECASE
)
_HEXNAME = re.compile(r"^[0-9a-f]{12,}$", re.IGNORECASE)
field_names = sorted(
    n for n in ((f.get("name", "") or "") for f in form_data.get("fields", []))
    if n and not _VOLATILE_FIELD.search(n) and not _HEXNAME.match(n)
)
```

- [ ] **Step 4:** Migration 0011: recompute fingerprint + `page_url = normalize_page_url(page_url)` for every DetectedForm; merge groups keeping earliest `first_seen_at` row. `pytest --create-db` → PASS.
- [ ] **Step 5: Commit** `fix(forms): stable fingerprints (ignore nonce/honeypot fields), merge duplicates`

### Task 6: Managed vs third-party embedded forms

**Files:**
- Modify: `apps/scripts/serializers.py` (`DetectedFormSerializer`), `frontend/src/components/forms-tab.tsx`, `frontend/src/lib/api.ts` (DetectedForm type), website detail page Forms tab count
- Test: `tests/scripts/test_form_serializer.py`

**Interfaces:**
- Produces: `is_managed: bool` on the form payload (`detection_type != "embedded"`); Forms tab headline counts managed forms only; embedded forms render in a separate "Third-party embedded forms" section labeled unverifiable.

- [ ] **Step 1:** Serializer test: embedded → `is_managed is False`, native/dom → True. Implement `is_managed = serializers.SerializerMethodField()`.
- [ ] **Step 2:** `pytest tests/scripts/test_form_serializer.py --create-db -v` → PASS.
- [ ] **Step 3:** Frontend: split `forms` into `managed` / `embedded`; headline `{managed.length} forms across {pages} pages`; tab badge count = managed; embedded section collapsed with copy "Managed by a third party — submissions can't be verified from the page."
- [ ] **Step 4:** `cd frontend && npm run build` → PASS.
- [ ] **Step 5: Commit** `feat(forms): count only WordPress-managed forms; separate third-party embeds`

### Task 7: Google Ads URL display

**Files:**
- Modify: `frontend/src/app/(dashboard)/websites/[id]/page.tsx:83-92` (`smartUrl`) and/or `frontend/src/components/scripts-tab.tsx` URL rendering

**Interfaces:**
- Produces: script URL display keeps identifying query param (`id`, `client`, `render`, `l`) so Google Ads shows `googletagmanager.com/gtag/js?id=AW-123456789` instead of a bare filename; full URL remains in tooltip/detail dialog.

- [ ] **Step 1:** Update `smartUrl` (and the scripts-tab equivalent) to re-append known identifying params from the parsed query.
- [ ] **Step 2:** `npm run build` → PASS; visual check of scripts list.
- [ ] **Step 3: Commit** `fix(scripts-ui): show identifying query params (AW-/GTM- ids) in script URLs`

### Task 8: Full verification

- [ ] `pytest --create-db` (whole suite) → PASS.
- [ ] `cd frontend && npm run build && npm run lint` → PASS.
- [ ] Commit any stragglers; summarize.
