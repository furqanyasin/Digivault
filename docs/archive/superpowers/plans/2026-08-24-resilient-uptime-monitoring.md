# Resilient Uptime Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop reporting live sites as down, and stop the platform's single egress IP from being blacklisted, without adding infrastructure.

**Architecture:** All server-side fetches of customer origins move behind one budgeted, honestly-identified HTTP client. A WAF block becomes a new `blocked` monitor status rather than an outage. A failing check is confirmed twice more before it counts. Before any down alert fires, the monitor consults `website.last_seen_at` — real-visitor ingest already recorded in the DB — and suppresses the alert if browsers were being served moments ago.

**Tech Stack:** Django 5.1, DRF, Celery, Redis (via `django_redis` cache), pytest.

**Spec:** [docs/superpowers/specs/2026-08-24-resilient-uptime-monitoring-design.md](../specs/2026-08-24-resilient-uptime-monitoring-design.md)

## Global Constraints

- Single egress IP. No new probe infrastructure, no multi-region.
- Mixed fleet (WordPress, Webflow, Wix, Shopify, custom) — no site-side agent may be required.
- Do **not** add routes to `apps/websites/wp_sso_snippet.py`; it forces every client to re-paste.
- Never impersonate a browser user-agent. Identity is honest and stable:
  `Mozilla/5.0 (compatible; Digivault-Monitor/1.0; +https://digivault.digilatics.co/bot)`
- Redis unavailability must never stop monitoring — the token bucket fails open.
- Corroboration may only ever **suppress** an alert; it may never mark a monitor `up`.
- Tests: `pytest`. Pass `--create-db` after any model/migration change.
- Existing `tests/monitors/test_retry_dedup.py` and `test_due_dispatch.py` must keep passing unmodified.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/common/outbound.py` | **New.** One HTTP client for all customer-origin fetches: identity headers, per-host token bucket, `Retry-After`/403 backoff, WAF block identification, SSRF guard. |
| `apps/monitors/liveness.py` | **New.** `corroborate_liveness(monitor)` — does real-visitor ingest contradict a failed probe? |
| `apps/monitors/checker.py` | HEAD→GET, `blocked` classification via `outbound.identify_block`. |
| `apps/monitors/tasks.py` | Confirmation re-check sequence; corroboration gate before alerting. |
| `apps/monitors/models.py` | `BLOCKED` status; `consecutive_blocks`; `blocked` excluded from uptime denominator. |
| `apps/monitors/views.py` | `MonitoringInfoView` — public allowlist info. |
| `apps/monitors/serializers.py` | `block_info` on `MonitorSerializer`. |
| `apps/websites/signals.py` | `retry_count: 1` → `3`. |
| `apps/websites/models.py` | `seo_scan_interval_days` default `7`; `blocked` in health score. |
| `apps/websites/tasks.py` | `run_due_passive_scans` — daily script scan with no snippet. |
| `apps/performance/tasks.py` | `run_due_checks` — weekly recurring PageSpeed. |
| `apps/site_health/seo_checker.py`, `apps/websites/wp_forms.py`, `apps/websites/views.py` | Migrated onto `apps/common/outbound.py`. |
| `config/settings/base.py` | New settings + beat entries. |

---

### Task 1: The shared outbound client

**Files:**
- Create: `apps/common/outbound.py`
- Test: `tests/common/test_outbound.py`

**Interfaces:**
- Produces:
  - `USER_AGENT: str`
  - `DEFAULT_HEADERS: dict[str, str]`
  - `class OutboundError(Exception)`, `class RateLimitedError(OutboundError)`, `class HostCoolingDownError(OutboundError)`
  - `registrable_host(url: str) -> str`
  - `identify_block(status_code: int, headers: Mapping[str, str], body: str) -> str` — returns a vendor name (`"Cloudflare"`, `"Wordfence"`, …) or `""`
  - `fetch(url, *, method="GET", timeout=30, headers=None, extra_headers=None, bypass_budget=False, read_bytes=65536) -> FetchResult`
  - `FetchResult` dataclass: `status_code: int`, `body: str`, `headers: dict[str, str]`, `elapsed_ms: int`, `final_url: str`

- [ ] **Step 1: Write failing tests** in `tests/common/test_outbound.py` covering:
  `test_registrable_host_strips_www_and_scheme`, `test_identify_block_cloudflare_challenge`,
  `test_identify_block_wordfence_body`, `test_identify_block_returns_empty_for_plain_500`,
  `test_budget_spaces_requests_per_host`, `test_budget_shared_across_www_variant`,
  `test_retry_after_sets_cooldown`, `test_repeated_403_escalates_cooldown`,
  `test_budget_fails_open_when_cache_unavailable`, `test_fetch_applies_ssrf_guard`.

- [ ] **Step 2:** Run `pytest tests/common/test_outbound.py -v` — expect ImportError.
- [ ] **Step 3:** Implement `apps/common/outbound.py`. Token bucket in `django.core.cache` (Redis-backed): key `outbound:last:{host}` for spacing, `outbound:count:{host}:{hour}` for the hourly ceiling, `outbound:cool:{host}` for backoff. Wrap every cache call in `try/except Exception` and continue on failure. Call `assert_public_url` before every request. Move `_BLOCK_PAGE_MARKERS`, `_MIN_PLAUSIBLE_PAGE_BYTES` and `_looks_like_block_page` here from `apps/websites/views.py`.
- [ ] **Step 4:** Run `pytest tests/common/test_outbound.py -v` — expect PASS.
- [ ] **Step 5:** Commit — `feat(common): one budgeted, honestly-identified outbound HTTP client`

---

### Task 2: `blocked` as a first-class monitor status

**Files:**
- Modify: `apps/monitors/models.py`, `apps/websites/models.py`
- Create: `apps/monitors/migrations/00XX_blocked_status.py` (via `makemigrations`)
- Test: `tests/monitors/test_blocked_status.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `Monitor.Status.BLOCKED == "blocked"`, `MonitorCheck.Status.BLOCKED == "blocked"`, `Monitor.consecutive_blocks: int`.

- [ ] **Step 1:** Write `tests/monitors/test_blocked_status.py`:
  `test_blocked_checks_excluded_from_uptime_denominator` (2 up + 1 blocked → 100.0, not 66.67),
  `test_all_blocked_gives_null_uptime`,
  `test_blocked_monitor_deducts_from_health_score_but_is_not_urgent`.
- [ ] **Step 2:** Run — expect FAIL (`BLOCKED` undefined).
- [ ] **Step 3:** Add `BLOCKED = "blocked", "Blocked"` to both `Status` classes and `consecutive_blocks = models.PositiveIntegerField(default=0)` to `Monitor`. In `recalculate_uptime`, `.exclude(status=MonitorCheck.Status.BLOCKED)` from both the total and the up count. In `Website.recalculate_health_score`, add a `Monitor.Status.BLOCKED in statuses` branch: `deductions += 3; warn = True`.
- [ ] **Step 4:** `python manage.py makemigrations monitors`, then `pytest tests/monitors/test_blocked_status.py -v --create-db` — expect PASS.
- [ ] **Step 5:** Commit — `feat(monitors): a WAF block is a status of its own, not downtime`

---

### Task 3: `check_http` — HEAD first, and name the blocker

**Files:**
- Modify: `apps/monitors/checker.py`
- Test: `tests/monitors/test_checker_http.py` (extend)

**Interfaces:**
- Consumes: `outbound.identify_block`, `outbound.DEFAULT_HEADERS`, `outbound.USER_AGENT`.
- Produces: `check_http(..., attempt: int = 1)`; result dicts may now carry `"status": "blocked"`.

- [ ] **Step 1:** Add tests: `test_head_falls_back_to_get_on_405`, `test_keyword_monitor_always_uses_get`, `test_wordfence_403_is_blocked_not_down`, `test_sucuri_403_is_blocked`, `test_unidentified_403_is_still_down`, `test_plain_500_is_still_down`, `test_attempt_3_sends_no_cache_header`.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Rewrite `check_http`: `attempt` selects method/headers (1 → HEAD, 2 → GET, 3 → GET + `Cache-Control: no-cache`); `keyword` forces GET on every attempt; 405/501 retries once as GET; replace `_challenge_message` with `outbound.identify_block` on both the success and `HTTPError` paths; when it names a vendor return `{"status": "blocked", …}` with a message naming the vendor and pointing at the allowlist page.
- [ ] **Step 4:** Run `pytest tests/monitors/test_checker_http.py -v` — expect PASS.
- [ ] **Step 5:** Commit — `fix(monitors): stop reporting a WAF block as an outage`

---

### Task 4: Confirmation re-checks before a failure counts

**Files:**
- Modify: `apps/monitors/tasks.py`, `config/settings/base.py`
- Test: `tests/monitors/test_confirmation.py`

**Interfaces:**
- Consumes: `check_http(..., attempt=)` from Task 3.
- Produces: `check_single_monitor(monitor_id: str, attempt: int = 1)`.

- [ ] **Step 1:** Write `tests/monitors/test_confirmation.py`: `test_first_failure_writes_no_check_and_requeues`, `test_third_failure_writes_one_check_and_increments`, `test_recovery_on_attempt_two_ends_sequence_and_writes_up`, `test_blocked_result_short_circuits_confirmation`.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Add `MONITOR_CONFIRM_ATTEMPTS = 3` and `MONITOR_CONFIRM_DELAYS = [15, 45]` to settings. In `check_single_monitor`, accept `attempt`; pass it to `run_check`; on a `down` result with `attempt < MONITOR_CONFIRM_ATTEMPTS`, log, re-queue with `apply_async(args=[monitor_id, attempt + 1], countdown=MONITOR_CONFIRM_DELAYS[attempt - 1])` and `return` before writing anything.
- [ ] **Step 4:** Run — expect PASS. Then `pytest tests/monitors/ -v` to confirm `test_retry_dedup.py` and `test_due_dispatch.py` still pass.
- [ ] **Step 5:** Commit — `feat(monitors): confirm a failure twice more before it counts`

---

### Task 5: Corroborate with real visitors

**Files:**
- Create: `apps/monitors/liveness.py`
- Modify: `apps/monitors/tasks.py`, `config/settings/base.py`
- Test: `tests/monitors/test_liveness.py`

**Interfaces:**
- Consumes: `Monitor.consecutive_blocks` (Task 2).
- Produces: `corroborate_liveness(monitor) -> tuple[bool, str]` — `(suppress, reason)`.

- [ ] **Step 1:** Write `tests/monitors/test_liveness.py`: `test_fresh_last_seen_suppresses_and_marks_blocked`, `test_stale_last_seen_does_not_suppress`, `test_monitor_without_website_does_not_suppress`, `test_website_never_seen_does_not_suppress`, `test_suppression_cap_eventually_alerts`, `test_corroboration_never_reports_up`, `test_exception_in_corroboration_falls_through_to_alerting`.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Add `LIVENESS_WINDOW_SECONDS = 600`, `LIVENESS_MAX_SUPPRESSED_CHECKS = 6`. Implement `corroborate_liveness`. Wire into `check_single_monitor`: on a confirmed `down`, call it; if it suppresses, record the check as `blocked`, bump `consecutive_blocks`, skip the alert. Reset `consecutive_blocks` to 0 on any non-blocked result.
- [ ] **Step 4:** Run — expect PASS.
- [ ] **Step 5:** Commit — `feat(monitors): don't alert down while real browsers are being served`

---

### Task 6: Fix the provisioning default and route every caller through the budget

**Files:**
- Modify: `apps/websites/signals.py:57`, `apps/site_health/seo_checker.py`, `apps/websites/wp_forms.py`, `apps/websites/views.py`
- Test: `tests/websites/test_monitor_provisioning.py`

**Interfaces:**
- Consumes: `outbound.fetch`, `outbound.DEFAULT_HEADERS`.

- [ ] **Step 1:** Write `test_auto_created_monitor_uses_retry_count_three`.
- [ ] **Step 2:** Run — expect FAIL (gets 1).
- [ ] **Step 3:** Change `"retry_count": 1` → `3`. Replace `seo_checker.fetch`'s body with a call to `outbound.fetch`. Replace `wp_forms`' bare `requests.get` with `outbound.fetch`. In `views.py`, delete the now-duplicated `_BLOCK_PAGE_MARKERS`/`_looks_like_block_page` and import from `outbound`; keep `?_dvv=` on these human-triggered actions only.
- [ ] **Step 4:** Run `pytest tests/websites/ tests/site_health/ -v`.
- [ ] **Step 5:** Commit — `fix(monitors): give auto-provisioned monitors the retry budget the model intends`

---

### Task 7: Make the monitor allowlistable

**Files:**
- Modify: `apps/monitors/views.py`, `apps/monitors/urls.py`, `apps/monitors/serializers.py`, `config/settings/base.py`
- Test: `tests/monitors/test_monitoring_info.py`

**Interfaces:**
- Produces: `GET /api/monitoring-info/` (AllowAny); `MonitorSerializer.block_info`.

- [ ] **Step 1:** Write `test_monitoring_info_is_public`, `test_monitoring_info_lists_egress_ips_and_user_agent`, `test_block_info_present_when_latest_check_blocked`, `test_block_info_absent_otherwise`.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Add `MONITOR_EGRESS_IPS = env.list("MONITOR_EGRESS_IPS", default=[])`. Implement the view returning `{user_agent, egress_ips, allowlist: {cloudflare, wordfence, sucuri, htaccess}}`. Add a `block_info` `SerializerMethodField`.
- [ ] **Step 4:** Run — expect PASS.
- [ ] **Step 5:** Commit — `feat(monitors): publish who we are so clients can allowlist us`

---

### Task 8: Monitoring that does not wait for the tracking script

**Files:**
- Modify: `apps/websites/models.py`, `apps/websites/tasks.py`, `apps/performance/tasks.py`, `config/settings/base.py`
- Create: `apps/websites/migrations/00XX_seo_interval_default.py`
- Test: `tests/websites/test_passive_monitoring.py`

**Interfaces:**
- Produces: `websites.run_due_passive_scans`, `performance.run_due_checks`.

- [ ] **Step 1:** Write `test_new_website_defaults_to_weekly_seo`, `test_passive_scan_skips_sites_scanned_today`, `test_passive_scan_skips_inactive_sites`, `test_performance_due_checks_skips_recently_checked`.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Change the field default `0` → `7` + data migration touching only rows still at `0`. Implement both tasks. Register beat entries: `run-due-passive-scans` daily 05:00, `run-due-performance-checks` Mondays 05:30.
- [ ] **Step 4:** Run `pytest tests/websites/ tests/performance/ -v --create-db`.
- [ ] **Step 5:** Commit — `feat(websites): keep watching sites that have no snippet yet`

---

## Self-Review

**Spec coverage:** §1 outbound client → Task 1 + 6. §2 `check_http` → Task 3, with the `blocked` status itself in Task 2. §3 confirmation → Task 4. §4 corroboration → Task 5. §5 allowlist surface → Task 7. §6 script-free monitoring → Task 8. Data model changes → Tasks 2 and 8. Settings table → distributed across the tasks that consume each setting. No gaps.

**Ordering note:** Task 2 must precede Tasks 3 and 5 (they emit `blocked`). Task 1 must precede 3 and 6. Task 3 must precede 4.

**Type consistency:** `identify_block` returns `str` (vendor name or `""`) throughout. `corroborate_liveness` returns `tuple[bool, str]` throughout. `check_single_monitor`'s second parameter is `attempt` in both the signature and the `apply_async` call.
