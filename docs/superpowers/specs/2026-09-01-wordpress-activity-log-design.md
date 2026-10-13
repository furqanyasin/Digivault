# WordPress Activity Log — Design

**Date:** 2026-09-01
**Status:** Implemented — all four phases, branch `feat/wp-activity-log-phase-0`
**Prior art:** [MALCARE-ARCHITECTURE.md](../../../MALCARE-ARCHITECTURE.md) — a read of MalCare Security 6.72, whose activity log this feature is benchmarked against.

---

## 1. Problem

Digivault detects WordPress plugin, theme and core changes today, but only by
inference: [`apps/scripts/wp_assets.py`](../../../apps/scripts/wp_assets.py)
reads `?ver=` off enqueued front-end assets and diffs consecutive ingests. That
approach has a documented ceiling, restated here because the whole design follows
from it:

* A plugin that enqueues no front-end JavaScript is invisible. SEO, backup,
  security and admin-only plugins are commonly in that group.
* `?ver=` is set by whoever enqueued the asset; a plugin that passes a build
  hash, the core version, or nothing cannot be version-tracked.
* **Nothing passive can ever say who did it.** `SiteEvent.actor` exists and is
  always blank.

Everything else an agency wants to know about a client's WordPress site — a new
administrator account, a role escalation, a burst of failed logins, a page
deleted, a file changed on disk — happens in wp-admin and never reaches the
front end at all. `SiteEvent.EventType` at
[`apps/site_health/models.py:44`](../../../apps/site_health/models.py) already
concedes the point in a comment: *"an edit is invisible without a WordPress-side
hook."*

This design adds that hook surface.

## 2. Scope

Four event families, chosen against agency accountability rather than MalCare's
security-product framing:

| Family | Rationale |
|---|---|
| **Users** | New admin accounts, role changes, login failures. Highest security value, smallest hook surface, pairs with existing suspicious-script detection. |
| **Plugins / themes, attributed** | Upgrades today's inference to *who and when*; closes the admin-only-plugin blind spot. |
| **Posts / pages** | Content changes on client sites the agency maintains. |
| **File integrity + WooCommerce** | Highest cost. File integrity is the strongest compromise signal available; Woo is included because commerce clients are where downtime costs money. |

Explicitly **out of scope**, and deliberately so: a firewall, malware scanning,
malware cleaning, 2FA, backups. See §9.

## 3. Constraints

**C1 — Snippet, not plugin.** The collector extends the existing WP Connect PHP
snippet ([`apps/websites/wp_sso_snippet.py`](../../../apps/websites/wp_sso_snippet.py)),
pasted into WPCode / Code Snippets. No `.zip`, no wordpress.org listing.

**C2 — One re-paste, ever.** CLAUDE.md: *"adding a route to `wp_sso_snippet.py`
obliges every client site to re-paste the snippet, so it is not a free change."*
The snippet must therefore be written **complete** on the first pass — every
hook for all four families — even though the backend consumes them in phases.
Backend phases require no further client contact.

**C3 — The snippet gains no new inbound capability.** MalCare's plugin grants
`app.malcare.com` arbitrary file writes, arbitrary SQL, and login-as-any-user
(§11 of the architecture read). Digivault's snippet grants role-mapped SSO and
form-config reads. The activity collector is hooks in, signed POST out; it adds
**zero** new remote-command surface. This is a positioning decision as much as a
security one.

**C4 — Fail open, fail quiet.** Consistent with `apps/common/outbound.py`, whose
token bucket fails open so Redis being down cannot stop monitoring. A collector
that errors must never break the client's site.

## 4. Architecture

```
Client WordPress site                          Digivault
─────────────────────                          ─────────
~35 core hooks
      │
      ▼
{prefix}digivault_events            HMAC-signed
  (buffer table, autoinc = seq)  ──── POST ────▶  /api/wp-activity/
      ▲                                               │
      │ shutdown flush (batched)                      ▼
      │ + wp_cron every 5 min                    seq-gap check
                                                      │
wp_cron daily: chunked                                ▼
wp-content file walk           ──── POST ────▶   SiteEvent  ◀── merge ── wp_assets
  (path, md5, size, mtime)                       (one timeline)     passive inference
      │                                               │
      └── no local baseline ──────────────────▶  FileManifest ── diff ──▶ file events
```

### 4.1 Snippet v2 — WordPress side

**Version arbitration.** The existing snippet wraps every helper in
`if ( ! function_exists( 'dvc_...' ) )`. A client who *adds* the v2 snippet
rather than replacing v1 gets v1's function bodies bound to v2's route
registrations — silently, with no error. Given that re-paste is this feature's
entire cost centre, "the paste half-worked and nobody noticed" is the failure
mode to design out.

MalCare solves the identical problem with version-suffixed class names
(`MCProtectFW_V672`), because their prepend WAF and plugin can be different
versions in one PHP process. We adopt the same:

* `define( 'DVC_VERSION', 2 )` guarded by `defined()`.
* All symbols suffixed: `dvc2_verify_token`, `dvc2_handle_sso`, …
* On load, if a **higher** `DVC_VERSION` is already defined, return immediately.
  Highest version wins; no half-merged state is reachable.

**Buffer table** `{$wpdb->prefix}digivault_events`, created lazily behind a
`dvc2_db_version` option guard:

| Column | Notes |
|---|---|
| `id` BIGINT AUTO_INCREMENT | **This is the sequence number.** See §4.2. |
| `occurred_at` DATETIME | Site-local time, sent as UTC. |
| `event_type` VARCHAR(40) | |
| `actor_login`, `actor_id`, `actor_ip` | `actor_id` because usernames get renamed. |
| `object_type`, `object_id` | |
| `summary` VARCHAR(500) | |
| `details` TEXT | JSON, **sliced to 1024 bytes** (MalCare's `logslicesize`). |
| `sent_at` DATETIME | Set when a row goes out in a flush; the row is **deleted** on ack. Unacked rows therefore survive to be re-sent (§4.2), and `id` keeps advancing across deletions so the sequence stays monotonic. |

Capped at **10 000 rows** — MalCare's `max_table_length` on their PHP error
store, adopted for the same reason: one hot hook in a loop must not fill a
client's database. On overflow the oldest unsent rows are dropped and a single
`buffer_overflow` event is recorded in their place.

**Hooks — approximately 35**, versus MalCare's ~80. We drop their multisite set
and their long-tail WooCommerce set (attributes, tax rates, download
permissions, shipping zones):

* *Users*: `wp_login`, `wp_login_failed`, `user_register`, `profile_update`,
  `set_user_role`, `delete_user`, `password_reset`, `after_password_reset`.
* *Plugins / themes*: `activated_plugin`, `deactivated_plugin`,
  `upgrader_process_complete`, `switch_theme`, `deleted_plugin`,
  `deleted_theme`, `_core_updated_successfully`.
* *Content*: `transition_post_status`, `before_delete_post`, `wp_trash_post`,
  `untrash_post` — filtered to post types `post` and `page`.
* *Commerce*: `woocommerce_order_status_changed`, `woocommerce_update_product`,
  `woocommerce_order_refunded`.

**Redaction.** Following MalCare's `logconfig.except`, an allowlist governs
which hook arguments reach `details`; everything else is dropped by key, not
truncated. `password_reset` and `profile_update` record *that* it happened and
by whom, never the value.

**Flush.** On `shutdown`, batched, `wp_remote_post` with a 2-second timeout,
plus a `wp_schedule_event` every 5 minutes as the safety net — a low-traffic
site may not fire `shutdown` often enough to matter, and a high-traffic one must
not flush per request. WP-cron is itself traffic-driven, which matches
Digivault's existing passive model.

**File integrity.** A separate daily `wp_schedule_event`, walking
`wp-content/{plugins,themes,mu-plugins}` in slices with a cursor stored in an
option. Reports `(path, md5, size, mtime)`. **No baseline is stored locally** —
Digivault holds it and diffs. MalCare markets "we don't bloat your database";
storing a 50k-row checksum table on the client would be doing the thing they
market against.

**Dead-man switch.** Every acked flush stores `dvc2_last_ack`. If it is older
than **7 days**, hooks stop registering and the buffer is truncated. This is not
optional: a snippet has no uninstall hook, so a client who cancels Digivault —
or a site we can no longer reach — would otherwise buffer into their database
forever. MalCare does the same thing with `bvwatchtime` on a 3-day window; we
use 7 because our flush cadence is slower and less chatty than their drain.

### 4.2 Transport

`POST /api/wp-activity/` — no DRF authentication class, authenticated instead by:

```
X-Digivault-Site:      <site_id>
X-Digivault-Timestamp: <unix seconds>
X-Digivault-Signature: hash_hmac('sha256', timestamp . '.' . raw_body, wp_sso_secret)
```

Rejected outside a **300-second** window, matching MalCare's `bvTime` replay
guard.

**We must not reuse the `php-errors` pattern.**
[`apps/site_health/views.py:51`](../../../apps/site_health/views.py) binds on
`Origin` / `Referer`, but a server-side PHP POST sends neither and the check is
`if origin:` — so it passes vacuously. Acceptable for PHP warnings; not for a
payload carrying usernames, email addresses and IPs. The shared secret already
exists on both ends; use it.

**Sequence gaps.** MalCare's `wtch` wing supports `enforce_auto_incr_check`: if
the table's `MAX(id)` is below the cloud's stored offset, the table was
truncated and the server is told `offset_reset_required` rather than silently
missing events. The push equivalent is the buffer's autoincrement `id`. Digivault
stores `Website.wp_connect_last_seq`; a batch whose first `id` exceeds
`last_seq + 1` means a flush was lost. The response then carries
`{"resend_from": <n>}` and the snippet re-sends unacked rows still in the buffer.

This yields push's latency with pull's delivery guarantee, for the cost of one
integer column — rather than building a second transport for reconciliation.

### 4.3 Data model

**Extend `SiteEvent`. Do not add a new model.** The correlation payoff (§4.5)
only exists if WordPress events share a timeline with SEO changes,
form-recipient changes and page discoveries. `occurred_at` is already the spine.

New fields:

| Field | Notes |
|---|---|
| `source` | `passive` \| `wp_connect` \| `manual`. Existing rows migrate to `passive`, except manual-entry rows. |
| `actor_ip` | `GenericIPAddressField`, null. |
| `actor_wp_id` | Integer, null. Usernames get renamed; IDs don't. |
| `object_type`, `object_id` | For linking a row to the post/user/plugin it concerns. |
| `sequence` | BigInteger, null for non-WP-Connect rows. |
| `category` | Stored, not derived — the enum reaches ~45 values and filtering needs an index. |

New index: `(website, category, -occurred_at)`.

`category` values: `users`, `plugins`, `themes`, `core`, `content`, `commerce`,
`files`, `seo`, `forms`, `discovery`.

`content` is post and page edits from hooks; `discovery` is the existing passive
`PAGE_DISCOVERED` — a URL the snippet had never reported before. They are
different observations and must not share a category, or the Activity tab's
content filter fills with URLs nobody edited.

New `Website` fields: `wp_connect_version` (int, 0 = not installed),
`wp_connect_last_ack` (datetime), `wp_connect_last_seq` (bigint).

**`FileManifest`** — one row per website, holding a compressed `path → md5` map
plus `walk_id` and `walked_at`. The diff is a pure function beside `DiffEngine`,
taking two maps and returning event dicts.

### 4.4 The passive / attributed merge

The obvious rule — suppress `wp_assets` inference whenever WP Connect is live —
is wrong. `upgrader_process_complete` does not fire for a plugin swapped in over
SFTP or installed by WP-CLI, so passive detection catches changes hooks
structurally cannot.

So both run, and merge:

1. Passive events are created on ingest exactly as today.
2. When an attributed event arrives matching a passive row on
   `(kind, slug, to_version)` within **24 hours**, the passive row is upgraded
   in place: it gains `actor`, `actor_ip`, `actor_wp_id`, and flips to
   `source=wp_connect`. No deferral; the timeline self-corrects within minutes.
3. A nightly task flags any passive plugin/theme event still unmatched after 24
   hours as `severity=warning`, summary *"changed outside wp-admin"*.

Step 3 is not dedupe housekeeping. **It is a compromise indicator**, and it
exists only because Digivault has both detection paths. MalCare, having only the
hook path, cannot produce it.

**File-walk diffing has the same shape of hazard as script diffing.** Slices
must accumulate into a pending manifest keyed by `walk_id` and diff only on
`walk_complete`; diffing each slice against the full baseline would report every
not-yet-walked file as removed — the identical failure mode CLAUDE.md documents
for snapshot-to-snapshot script diffs.

### 4.5 Correlation — the part that is not a clone

`GET /api/websites/{id}/timeline/?around=<iso>&window=30m`

Interleaves `SiteEvent`, `down`/`blocked` `MonitorCheck`, `PhpError` and
`ScriptChange` into one ordered feed:

> Site went down 14:32 — plugin `wp-rocket` updated 14:31 by `jdoe` from
> 41.x.x.x; three PHP fatals at 14:31:40 in `wp-rocket/inc/Engine.php`.

MalCare's activity log is a flat searchable list. It cannot answer this, because
they do not hold your uptime data. This endpoint is the reason to build the
feature rather than the log itself.

### 4.6 Retention

`SiteEvent` is currently the **only** event table in the codebase with no purge
task — `ActivityLog` (90d), `Notification` (90d), `PhpError`, `MonitorCheck`
(35d), `ScriptSnapshot` (90d) and `PerformanceReport` (365d) all have one.
Adding post/page/commerce volume across every client without one is the single
change here most likely to cause real harm.

`site_health.purge_old_site_events`, tiered:

* `users`, `plugins`, `themes`, `core`, `files` → **365 days** (agencies need
  the audit trail).
* everything else → **90 days**.

Scheduled in `CELERY_BEAT_SCHEDULE` alongside the existing weekly purges, clear
of the 04:00–07:00 window where the SEO, scan and WP sweeps already contend for
the per-host budget.

### 4.7 API and UI

The current list view
([`apps/site_health/views.py:100`](../../../apps/site_health/views.py)) is a hard
`[:200]` slice with no filters and no pagination. That is not parity with
MalCare, which filters by user, event type and date range and searches full
history. Replace with real pagination plus `category`, `event_type`, `actor`,
`since`, `until`, and `q` (substring on `summary`).

**Frontend: extend the existing Change Log tab. Do not add an Activity tab.**

The activity log is per-website and lives inside the website detail tabs. That
page already carries two history surfaces:

* the **Change Log** tab
  ([`frontend/src/app/(dashboard)/websites/[id]/page.tsx:394`](../../../frontend/src/app/(dashboard)/websites/[id]/page.tsx)),
  which merges `ScriptChange` and `SiteEvent` into one time-ordered feed — this
  is already the site timeline;
* a **User Activity** card fed by the team-wide `apps/audit` `ActivityLog`,
  which records what *Digivault* users did, not what happened on the client's
  WordPress site.

WordPress events are `SiteEvent` rows, so they flow into Change Log with no new
tab. Adding one would put a third history surface on the same page and force
the reader to guess which of two timelines a plugin update landed in — and it
would contradict §4.3, whose whole argument is that one timeline is the point.

So Change Log gains:

* the filter bar — `category`, `actor`, date range, search;
* category defaults that keep it readable once post/page/commerce volume
  arrives (security and script categories on by default; content and commerce
  off until asked);
* the "what changed around this time" panel from §4.5, on any incident.

The name **Change Log** stays. "Activity" is already spoken for on that page by
the team-wide audit card, and renaming either one invites exactly the confusion
this section exists to avoid.

### 4.8 Alerts

New `AlertRule` event types routed through the existing pipeline and
`get_backend(channel)`:

* `wp.admin_user_created`
* `wp.role_escalated`
* `wp.login_failed_burst`
* `wp.core_file_changed`
* `wp.plugin_changed_outside_admin` (the §4.4 signal)

### 4.9 Rollout instrumentation

`wp_connect_version` and `wp_connect_last_ack` surface as a badge on the
websites list, filterable. A re-paste campaign across every client is impossible
to run without knowing who is still on v1 — and this is the easiest piece to
forget, because nothing user-facing depends on it. It ships in Phase 0.

## 5. Phasing

| Phase | Contents | Client contact |
|---|---|---|
| **0** ✅ | Snippet v2 (all hooks, all families), transport, ingest endpoint, seq-gap handling, `SiteEvent` extension (§4.3), `FileManifest` **storage only, no diffing**, `Website` fields, tiered retention purge (§4.6), rollout badge. Every family is **persisted** from day one; none is surfaced. | **The one re-paste.** |
| **1** ✅ | Users + attributed plugins/themes surfaced: merge rule (§4.4), security alert rules (§4.8), filterable API and Change Log filter bar (§4.7). | None |
| **2** ✅ | Posts/pages + WooCommerce surfaced; per-site ingest rate limiting. | None |
| **3** ✅ | File integrity **diffing** (walk diff, file events, alert rule) + the correlation endpoint (§4.5). | None |

Two things are deliberate about this split.

`FileManifest` **stores** from Phase 0 but only **diffs** from Phase 3, for the
same reason — the snippet's daily walk starts the moment it is pasted, and there
is no way to ask it for only some families. Storing early also means Phase 3
lands against a baseline that already exists, so file changes are detectable on
day one of that phase rather than a day later.

The model extension and the retention purge sit in **Phase 0, not Phase 1**.
Once the snippet is pasted it starts sending all four families immediately —
there is no way to ask it for only some — so if `SiteEvent` cannot yet hold them
they are silently discarded, and the client's first week of history is lost for
nothing. The purge ships with them for the same reason: volume arrives at paste
time, not at surfacing time.

Because Phase 0 persists attributed events while the §4.4 merge does not land
until Phase 1, `source=wp_connect` rows are **excluded from the existing events
list view** for the duration of Phase 0. Without that exclusion a plugin update
would show twice — once inferred, once attributed — on every site that has
re-pasted, for as long as Phase 1 takes.

Phase 0 therefore ships no user-visible value. That is the price of C2 — the
expensive step happens once, and everything after it is ours to schedule.

**Each phase gets its own implementation plan.** This spec is the shared design;
it is not a single plan document, and Phase 0 alone is large enough to warrant
one of its own.

## 6. Testing

Per CLAUDE.md conventions:

* `--create-db` is required after the migrations in Phases 0–3.
* Celery is eager in tests, so a POST to `/api/wp-activity/` runs the pipeline
  inline, exactly as `/api/ingest/` does.
* The `no_network_in_tests` autouse fixture is sufficient — the flush is
  **inbound**, so no new outbound mocking is needed. The file-walk path adds no
  outbound calls either.
* `response.data` is the raw payload; assert `resp.data["..."]`, not
  `resp.data["data"]`.

Pure-function tests, no DB, mirroring `test_diff_engine.py`:

* Manifest diff: added / removed / modified / unchanged, and the
  **partial-walk case** — an incomplete slice set must produce no removals.
* Sequence-gap detection: contiguous, gapped, replayed, and reset-to-zero.
* HMAC verification: valid, wrong secret, expired timestamp, tampered body.

Integration tests:

* Passive event upgraded in place by a matching attributed event.
* Passive event unmatched after 24h flagged `changed outside wp-admin`.
* Buffer overflow produces exactly one `buffer_overflow` event.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Client adds v2 alongside v1 instead of replacing | Version-suffixed symbols + highest-version-wins bail (§4.1). |
| Client never re-pastes | Rollout badge (§4.9); passive detection continues unchanged for them. |
| Event volume from a busy Woo site | 10k buffer cap, 5-minute batching, tiered retention. |
| Flush adds latency to admin requests | Buffer-then-flush; never a POST inside a hook. |
| Cancelled client keeps buffering forever | 7-day dead-man switch (§4.1). |
| File walk times out on a large site | Chunked with a cursor; diff only on `walk_complete`. |
| Ingest endpoint abused | HMAC over body + 300s replay window; per-site rate limit. |

## 8. Rejected alternatives

**A real WordPress plugin.** Gets WP-cron for free, self-updates, and makes this
the last manual client step ever. Rejected in favour of staying with the snippet
already in use. Note the cron argument turned out not to favour the plugin —
`wp_schedule_event` works from a snippet, needing only code on `init`.

**Digivault pulls a `digivault/v1/activity` route.** This is what MalCare
actually does (`wtch` wing drains `wp_bv_activities_store` with offset/limit),
and it would reuse `wp_forms.py`'s signed-URL helper and `outbound.py`'s
token bucket and SSRF guard verbatim. Rejected because it silently collects
nothing on WAF-blocked sites — which CLAUDE.md documents as a first-class,
recurring condition with its own `blocked` status. Outbound POSTs from the
client's server work where our inbound requests do not.

**Push plus a reconciling pull.** Superseded by the sequence-gap mechanism
(§4.2), which delivers the same guarantee for one integer column.

**A separate `WpActivityEvent` model.** Rejected: it fragments the timeline and
forfeits §4.5, which is the feature's actual differentiator.

## 9. Deliberately not built

MalCare's plugin is a thin agent for a cloud control plane that can write any
file, run any SQL, and log in as any user. That is inherent to what remote
malware cleaning and remote backup *are*. Digivault is not that product, and
adopting that trust model to gain an activity log would be a bad trade.

Not in scope, now or later under this design: WAF / rule engine, malware
scanning or cleaning, backups, 2FA, IP blocking, login protection.

**Noted for separate consideration:** MalCare's `form_testing/` module submits
real test entries through CF7 / WPForms / Elementor, bypassing CAPTCHA and spam
plugins. Digivault already has a Forms tab that reads recipients but cannot
prove delivery. *"This client's contact form is actually reaching them"* is
plausibly higher value per unit of effort than half of this design. It is not
part of this spec.


---

## 10. What shipped, and where it differed from this spec

All four phases are implemented. Five things ended up different from the design
above, each for a reason worth recording.

**`Notification` gained a `site_event` FK.** Not in the original design, which
assumed the existing alert plumbing would carry a WordPress event. It would not:
`Notification` links only to a `ScriptChange`, so an activity alert would have
arrived carrying nothing but a website name — which is exactly what the
performance-regression path does today, and why those alerts say nothing useful.

**Roles are ranked, not a privileged set.** §4.8 named
`wp.role_escalated` without saying how escalation is detected. A flat set fails
the case that matters most: editor → administrator reads as privileged on both
sides and stays silent. `_ROLE_RANK` orders them and alerts only on upward
movement into privilege.

**File events collapse per directory.** Not in the spec. Deleting a plugin
removes hundreds of files, and one row each would make the timeline useless on
exactly the day something big happened. Above ten changes in a directory, the
directory is reported instead — and `is_sensitive_path` promotes executable code
appearing under `uploads/` to CRITICAL, which is the shape of nearly every
WordPress backdoor.

**Manifests are pruned to the last two.** Each holds a path → md5 map for the
whole of `wp-content`; only the previous complete walk is ever read, so keeping
history grew unboundedly for no benefit.

**The Change Log filter bar drives server-side query params, not a client-side
array filter.** The endpoint caps at 500 rows, so filtering in the browser would
filter a truncated list and silently hide older matches.

### Still outstanding

`DVC2_WALK_SLICE` is 400 files per daily cron tick. A 50k-file site takes months
to complete one walk, so file-integrity diffing is effectively inert on large
sites until the slice size rises or the walk cron runs more often. Phase 3's
diffing is correct and tested; its *cadence* is not yet fit for a big site.
