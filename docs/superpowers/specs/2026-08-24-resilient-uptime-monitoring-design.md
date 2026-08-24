# Resilient uptime monitoring from a single egress IP

**Date:** 2026-08-24
**Status:** Approved

## Problem

Two complaints, one root cause.

**Sites report down while they are live.** The monitor calls `check_http`
(`apps/monitors/checker.py`), which makes one `urllib` request from the platform's
single public IP with `User-Agent: Digivault-Monitor/1.0`. Wordfence, Sucuri,
ModSecurity, LiteSpeed and Cloudflare's Bot Fight Mode all answer an unrecognised
non-browser agent with 403. `check_http` only downgrades a 403 to `degraded` when
the response carries `cf-mitigated: challenge` or a `server` header of
`cloudflare`/`sucuri`; every other WAF's block falls through to `"status": "down"`.
The block becomes the outage report.

The alert then fires on the very first such response, because
`_create_uptime_monitor_db_only` (`apps/websites/signals.py`) provisions every
auto-created monitor with `retry_count: 1` — overriding the model's own default of
3. One 403, one TCP reset, one slow DNS lookup is a page-out.

**The IP gets blacklisted.** The monitor is not the only caller. The same IP also
runs the SEO checker (up to `MAX_PAGES = 15` page fetches per scan,
`apps/site_health/seo_checker.py`), the snippet verifier and the homepage scan —
both of which append a random `?_dvv=` cache-buster specifically to defeat CDN
caching, which is indistinguishable from scanning — plus `wp_forms` sync. Nothing
coordinates them. There is no per-host request budget anywhere in the codebase, no
`Retry-After` handling, and no backoff after a 429. A rate-limit response is
answered by continuing at the same rate.

Compounding both: the platform already holds a perfect, unblockable liveness
signal and never consults it. `apps/scripts/tasks.py` bumps `website.last_seen_at`
on every ingest, which arrives from a real visitor's browser. A site whose
`last_seen_at` is two minutes old is provably serving real users, whatever the
probe thinks.

**Secondary complaint: nothing happens until the tracking script is installed.**
Uptime monitoring does in fact start immediately — the post-save signal creates the
Monitor. What never starts is everything else: `seo_scan_interval_days` defaults to
`0` (off), the performance check runs exactly once at creation and never again, and
the server-side scan only ever runs when a human clicks it. A freshly added site
looks dead in the dashboard even though its monitor is ticking.

## Constraints

- **One egress IP. No new infrastructure.** Multi-region probing, the mechanism
  UptimeRobot's accuracy actually rests on, is off the table. Everything has to be
  earned from one box.
- **Mixed fleet** — WordPress alongside Webflow, Wix, Shopify and custom builds. No
  site-side agent covers it, so the design is external-first.
- Adding a route to `apps/websites/wp_sso_snippet.py` obliges every client site to
  re-paste the snippet (see CLAUDE.md). A WP heartbeat route is therefore not free,
  and would only cover a subset of a mixed fleet. Out of scope.

## Approach

Harden the prober, and stop treating the prober as the only witness.

Rejected alternatives:

- **Browser impersonation.** Sending Chrome's UA and header set beats naive WAFs
  today, but from a single IP it is caught on TLS fingerprint — urllib's JA4 looks
  nothing like Chrome's — which gets the IP banned harder and with no appeal, and
  permanently disqualifies Digivault from Cloudflare's Verified Bots programme.
  Because these are the agency's own clients' sites, allowlisting is genuinely
  available to us in a way it is not to an anonymous scraper. Honest, stable,
  documented identity is the only posture that compounds.
- **Outsourcing the probe** to UptimeRobot's or BetterStack's API. Solves
  blacklisting instantly, since their IPs are allowlisted everywhere, and buys
  multi-region for free. Rejected on per-monitor cost, vendor lock, and because it
  addresses roughly a quarter of the problem: the SEO checker, verifier and scan
  action would go on hammering the IP unchanged.
- **A WordPress heartbeat plugin route.** ManageWP's model, and Digivault has most
  of the machinery. Rejected under the re-paste constraint above plus the mixed
  fleet — it would be a second system covering a minority of sites.

## Components

### 1. `apps/common/outbound.py` — one client, one budget

Every server-side fetch of a customer URL routes through a single module. It owns:

**Identity.** One user-agent constant, following UptimeRobot's formula:

```
Mozilla/5.0 (compatible; Digivault-Monitor/1.0; +https://digivault.digilatics.co/bot)
```

The `Mozilla/5.0 (compatible; …)` prefix satisfies naive UA sniffers that reject
anything not starting with `Mozilla`; the `+URL` gives WAF vendors and site owners
something concrete to allowlist. Accompanied by real `Accept` and
`Accept-Language` headers, because a request with no `Accept` at all reads as a bot
to every bot-management edge.

**A per-host token bucket** in Redis, keyed on the registrable domain so
`example.com` and `www.example.com` share one budget. Two limits, both settable:
a minimum spacing between requests (`OUTBOUND_MIN_INTERVAL_SECONDS`, default 20)
and an hourly ceiling (`OUTBOUND_MAX_PER_HOUR`, default 60). Callers that exceed
the budget raise `RateLimitedError` rather than blocking a worker.

**Per-host backoff.** A 429 or 503 with `Retry-After` sets a Redis cooldown key for
that host; requests during the cooldown raise `HostCoolingDownError` without
touching the network. Repeated 403s from one host escalate the cooldown
exponentially, capped at one hour.

**Block detection.** `_BLOCK_PAGE_MARKERS` and `_looks_like_block_page` move here
out of `apps/websites/views.py`, joined by a header-based `identify_block`
returning the vendor name when one of these matches:

| Signal | Vendor |
|---|---|
| `cf-mitigated: challenge`, `server: cloudflare` | Cloudflare |
| `x-sucuri-block`, `server: sucuri/cloudproxy` | Sucuri |
| body contains `wordfence` / `generated by wordfence` | Wordfence |
| `server` contains `mod_security`, body `mod_security` | ModSecurity |
| `server: litespeed` with 403 | LiteSpeed |
| `x-imunify360-request-id` | Imunify360 |
| `server: awselb` / `x-amzn-waf-*` with 403 | AWS WAF |
| `server: akamaighost` with 403 | Akamai |
| `x-iinfo`, `x-cdn: incapsula` | Imperva |

The monitor, the SEO checker (`fetch`), the scan and verify actions in
`apps/websites/views.py`, and `apps/websites/wp_forms.py` are all migrated onto
this client. This is the piece that actually stops the blacklisting: the SEO scan's
15 rapid fetches look far more like a scanner than the monitor's one request does.

The SSRF guard (`apps/common/ssrf.assert_public_url`) is applied inside the client,
so every caller inherits it rather than remembering to call it — the monitor
currently does not.

### 2. `check_http` — a block is not an outage

Three changes to `apps/monitors/checker.py`:

**Method.** Try `HEAD` first, fall back to `GET` on 405 or 501, and always use
`GET` when a `keyword` is configured (a HEAD has no body to search). Cuts
bandwidth by roughly 95% on the common path, which is itself a rate-limit
reduction.

**Classification.** Replace `_challenge_message`'s two-vendor check with
`outbound.identify_block`. Any identified block returns a new status, `blocked`,
carrying a message naming the vendor and the fix.

**`blocked` as a first-class status.** Added to `Monitor.Status` and
`MonitorCheck.Status`. It never fires a down alert and never increments
`consecutive_failures`. It is excluded from the uptime-percentage denominator in
`recalculate_uptime` — a period we could not observe is not a period of downtime,
and counting it as either up or down is a lie. In `recalculate_health_score` it
deducts 3 points and sets `warn`, so the site surfaces as needing attention
without being reported as broken.

### 3. Confirmation re-checks before declaring down

UptimeRobot re-checks up to three times, 10–20 seconds apart, before marking a
monitor down. `check_single_monitor` gains an `attempt` argument, default 1.

On a `down` result with `attempt < CONFIRM_ATTEMPTS` (3), the task writes **no**
`MonitorCheck` row, does not touch `consecutive_failures`, and re-queues itself via
`apply_async(countdown=…)` at 15s and then 45s. Only the third consecutive failure
records a check and increments the counter. An `up`, `degraded` or `blocked` result
on any attempt records normally and ends the sequence.

Each attempt varies its request shape so a single WAF rule cannot manufacture three
identical failures: attempt 1 `HEAD`, attempt 2 `GET`, attempt 3 `GET` with
`Cache-Control: no-cache`. Per-host spacing is bypassed for confirmation attempts —
three requests inside a minute during a suspected outage is proportionate, and it
is bounded at three.

`last_checked_at` is already claimed by `run_due_checks` before dispatch, so a
confirmation sequence in flight cannot be re-dispatched by a later beat tick.

### 4. Corroboration from real visitors

Before `check_single_monitor` fires a down alert, `corroborate_liveness(monitor)`
in `apps/monitors/liveness.py` asks whether the site is demonstrably serving
traffic. It returns `True` when the monitor has a `website` whose `last_seen_at` is
within `LIVENESS_WINDOW_SECONDS` (default 600).

When it does, the monitor is recorded as `blocked` rather than `down`, no alert
fires, and an action card is raised telling the operator that monitoring is being
blocked and offering the allowlist instructions.

The guard rails matter more than the rule:

- It can only ever **suppress** an alert. It can never mark a monitor `up`, so it
  cannot invent uptime.
- It requires a linked `website` with a non-null `last_seen_at`. Sites without the
  snippet, and sites that have never reported, are unaffected.
- The window is short. Ten minutes of silence and corroboration stops, so a real
  outage is reported one window late at worst rather than never.
- Suppression is capped: `LIVENESS_MAX_SUPPRESSED_CHECKS` (default 6) consecutive
  suppressions in a row, after which the down alert fires anyway with the
  corroboration noted in the message. A permanently blocked monitor must not go
  permanently silent.

### 5. Allowlist surface

`GET /api/monitoring-info/` (unauthenticated, cached) returns the egress IP —
`MONITOR_EGRESS_IPS`, a settings list — the user-agent string, and ready-made
allowlist rules for Cloudflare, Wordfence, Sucuri and `.htaccess`. A public page at
`/bot` on the frontend renders it, which is where the `+URL` in the user-agent
points.

`MonitorSerializer` gains a `block_info` object when the monitor's latest check was
`blocked`: the vendor name, when it started, and a link to the page. The website
detail page renders it as an action card.

### 6. Monitoring that does not wait for the script

- `Website.seo_scan_interval_days` default `0` → `7`. A data migration moves
  existing sites still sitting on the old default, and only those.
- A new `websites.run_due_passive_scans` beat task, daily at 05:00 UTC, runs the
  existing server-side scan (script extraction from the homepage) for every active
  site whose last scan is older than a day. One request per site per day, through
  the shared budget. Script detection then works with no snippet installed.
- A new `performance.run_due_checks` beat task, weekly, re-runs PageSpeed for
  active sites. This calls Google's API, not the customer's origin, so it carries
  no blacklist risk.
- The scheduled paths must not send the `?_dvv=` cache-buster. It stays only on the
  human-triggered scan and verify actions, where a fresh read is the point.

## Data model changes

- `Monitor.Status` and `MonitorCheck.Status` gain `BLOCKED = "blocked"`.
- `Monitor.consecutive_blocks` — `PositiveIntegerField(default=0)`, backs the
  suppression cap.
- `Website.seo_scan_interval_days` default `0` → `7`, plus a data migration.
- No new tables.

## Error handling

- Every new outbound failure mode (`RateLimitedError`, `HostCoolingDownError`)
  results in **no** `MonitorCheck` row and no state change. A check we declined to
  make is not evidence about the site. It is logged and the monitor stays due.
- `corroborate_liveness` is wrapped: any exception means no corroboration, so the
  alert fires. Failing toward alerting is the safe direction.
- Redis being unavailable must not stop monitoring. The token bucket fails open —
  logged at warning, request proceeds.

## Testing

- `tests/monitors/test_checker_http.py` extends: HEAD→GET fallback on 405; each
  WAF vendor's fingerprint classified `blocked`; a genuine 500 still `down`; a 403
  from an unidentifiable server still `down` (we do not blanket-excuse 403s).
- `tests/monitors/test_confirmation.py`: one failure writes no check and re-queues;
  three write one check and increment; a recovery on attempt 2 ends the sequence.
- `tests/monitors/test_liveness.py`: fresh `last_seen_at` suppresses and marks
  `blocked`; stale does not; no linked website does not; the suppression cap
  eventually alerts; corroboration never produces `up`.
- `tests/common/test_outbound.py`: spacing enforced per registrable domain;
  `Retry-After` honoured; 403 escalation; fails open when Redis is down; SSRF guard
  applied.
- `tests/monitors/test_uptime_excludes_blocked.py`: `blocked` checks are absent
  from the uptime denominator.
- Existing `test_retry_dedup.py` and `test_due_dispatch.py` must keep passing
  unchanged — the retry/dedup contract is not being altered, only fed better input.

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `MONITOR_USER_AGENT` | the UA above | Single source of identity |
| `MONITOR_EGRESS_IPS` | `[]` | Published for allowlisting |
| `MONITOR_CONFIRM_ATTEMPTS` | `3` | Failures before a check is recorded |
| `MONITOR_CONFIRM_DELAYS` | `[15, 45]` | Seconds between attempts |
| `LIVENESS_WINDOW_SECONDS` | `600` | Ingest recency that corroborates |
| `LIVENESS_MAX_SUPPRESSED_CHECKS` | `6` | Cap before alerting anyway |
| `OUTBOUND_MIN_INTERVAL_SECONDS` | `20` | Per-host spacing |
| `OUTBOUND_MAX_PER_HOUR` | `60` | Per-host hourly ceiling |

## Out of scope

Multi-region probing, Cloudflare Verified Bots enrollment (needs reverse DNS on the
VPS, which is a hosting change), a WordPress heartbeat route, and any form of
browser impersonation.
