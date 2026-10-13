# Architecture review — remediation plan

Findings from the system-design review of 2026-09-18. Ordered by what has to be
true before the next item is safe to do, not by severity alone.

Status key: `[ ]` not started · `[~]` in progress · `[x]` done · `[-]` deferred (with reason)

---

## Wave 1 — Silent-failure bugs (small, isolated, no design decisions)

Each of these is a defect where the system reports success while doing nothing,
or does something it documents as forbidden. They touch few lines and nothing
depends on them, so they go first.

- [x] **1. `critical` severity is unroutable.** `AlertService._SEVERITY_LEVELS`
      omits `critical`, so the highest-severity change scores 0 and matches no
      rule. `AlertRule.min_severity` choices omit it too. Three definitions of
      one vocabulary. → one shared ordered enum.
      `apps/alerts/services.py`, `apps/alerts/models.py`
- [x] **2. Heatmap ingest answers 403 to every post from a `https://www.` site.**
      Fifth inlined copy of the origin check, with the `www.`-before-scheme bug
      the other four had. → call `ingest_origin.origin_matches`.
      `apps/heatmap/views.py`
- [x] **3. `deliver_notification.delay()` fires inside the open transaction.**
      Worker can read before commit; a retry re-sends. → `transaction.on_commit`.
      `apps/scripts/tasks.py`
- [x] **4. `sync_wp_form_recipients` is a duplicate of the API sweep and skips
      the auth-failure guard**, re-hitting sites with known-bad credentials an
      hour before the sweep written to avoid exactly that. → delete task + beat entry.
      `apps/websites/tasks.py`, `config/settings/base.py`
- [x] **5. `.env.production` is baked into the Docker image** (`.dockerignore`
      excludes `.env` only, Dockerfile does `COPY . .`). → ignore it and the
      other repo cruft.
      `.dockerignore`
- [x] **6. Settings referenced but never defined.** `WPSCAN_API_KEY` (CVE lookup
      permanently off, health score falls back to a hardcoded plugin-name list)
      and `SNIPPET_CDN_URL` (dev/test emit a snippet pointing at a host with no
      DNS). → declare both in `base.py`.
      `config/settings/base.py`
- [x] **7. `recalculate_all_health` skips every site without the snippet**, so
      time-based domain/SSL/hosting deductions never decay for them.
      `apps/websites/tasks.py`

## Wave 2 — Unguarded outbound calls (SSRF + egress-reputation)

The outbound layer exists and is correct; these are the callers that route
around it. Doing them after Wave 1 because they need `outbound.fetch` to grow
one option.

- [x] **8. Slack webhook delivery is an unguarded SSRF sink.** User-supplied URL,
      `urlopen`, default opener, unguarded redirects, no role gate on who can
      create the rule. → host allowlist + guarded fetch.
      `apps/alerts/delivery.py`
- [x] **9. `scan` and `verify_snippet` bypass the whole outbound layer** — raw
      `requests.get`, spoofed Chrome UA, no budget, no cooldown, **no SSRF guard
      on redirect hops**. → route through `outbound.fetch`.
      `apps/websites/views.py`

## Wave 3 — Authorization

- [x] **10. RBAC is defined but wired to 4 views out of ~100.** A `viewer` can
      create and delete websites and monitors, rename the team, write alert
      rules, import/export the client book, and trigger scans. → apply
      `RolePermission` across write surfaces.
      `apps/common/permissions.py` + every write view

## Wave 4 — Throughput (needs measurement, changes behaviour under load)

- [x] **11. Heatmap aggregation is 2–3 queries per cell, ≤5000 cells/payload.**
      → single `bulk_create(update_conflicts=True)`.
      `apps/heatmap/tasks.py`
- [x] **12. One Celery worker, concurrency 2, one queue.** Monitor timeouts stall
      ingest. → queue routing (`ingest` / `monitors` / `slow`) + separate workers.
      `config/settings/base.py`, compose files
- [x] **13. Every ingest post locks the Website row through ~15 queries**,
      including a full Python-side scan of the site's scripts, a per-script
      scope UPDATE loop, and an 8-query health recalc. Snippet posts 6+ times
      per pageview. → debounce the two sweeps, narrow the lock.
      `apps/scripts/tasks.py`

## Wave 5 — Infrastructure & process

- [x] **14. Redis is one un-persisted instance serving cache + broker + results
      + channel layer on one DB index.** A restart drops the task backlog, every
      login session, every rate-limit counter and every outbound cooldown.
- [x] **15. No CI.** 174 test files nothing runs automatically.
- [x] **16. No health/readiness endpoint, no container healthchecks.**
- [-] 17. Deploy has no rollback and no backup step. *(Backup: done —
      `backup-db.sh` nightly, off-server via rclone, see
      `docs/runbooks/backups.md`. Rollback: still deferred — needs a
      registry/tagging decision that is an infra call, not a code change.)*

## Wave 6 — Contracts & structure

- [x] **18. Pagination truncation is still live in ~20 frontend call sites.**
      `api.get()` on list endpoints silently returns 25 rows with no error.
- [-] 19. No API schema; `frontend/src/lib/api.ts` is hand-maintained.
      *(Deferred — drf-spectacular adds a dependency and a build step; worth
      doing, but it is a project rather than a fix.)*
- [x] **20. WebSocket sessions never re-authorize** — a removed team member keeps
      receiving that team's alerts until the tab closes.
- [-] 21. UUIDv4 PKs on the highest-write tables; unique constraints over
      unbounded `TextField` URL columns. *(Deferred — both need data migrations
      over the largest tables in the system; schedule separately.)*

---

## Verification status

**The test suite has not been run against these changes.** The `.venv` in this
repo is broken — its `pyvenv.cfg` points at a base interpreter
(`…/Python312/python.exe`) that no longer exists, and it was created for a
different project (`D:\tools-working\scdb`). The only interpreter on the machine
is Python 3.14, which Django 5.1 does not support, and neither Postgres nor
Redis is running locally.

What *was* verified:

- Every changed Python file byte-compiles.
- The frontend type-checks clean (`npx tsc --noEmit`) — and the new `api.get`
  guard caught four list call sites that the mechanical conversion had missed.

What still needs a run on a working environment:

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements/development.txt
docker compose up -d db redis          # or a local Postgres + Redis
pytest --create-db
python manage.py makemigrations --check --dry-run
docker compose -f docker-compose.production.cloudpanel.yml config   # YAML/compose validity
```

The new CI workflow does all of the above on every push, so the second run of it
is the real verification.

## Follow-ups this work surfaced

- **Three tests have been failing since commit `516099b`.** `scan` grew a
  `snippet_status` gate and `tests/websites/test_scan_forms.py` was never
  updated, so all three of its endpoint tests got a 409. Fixed here — but the
  fact that it sat unnoticed is the argument for item 15.
- **Noise-script cleanup now only runs when an ingest changes something.** It is
  a backfill for rows stored before the tracked-category filter reached ingest,
  so this is correct, but a site with no traffic will keep its old noise rows. A
  one-off management command would finish the job properly.
- **`websites/signals.py` calls `.delay()` from a `post_save` receiver**, not
  through `transaction.on_commit`. There is no bug today (nothing wraps website
  creation in `atomic`), but it is the same shape as the one fixed in item 3 and
  would break silently the moment someone adds a transaction.
- **`celery-beat` has no healthcheck** — there is no equivalent of `inspect
  ping` for it. The existing `common.system_heartbeat` dead-man switch covers
  it, but only if `HEARTBEAT_PING_URL` is actually set.
- **A lint rule would be a better guard than the type trick** for `api.get` on
  lists. The compile error works, but its message arrives at the assignment
  site rather than the call.

---

## First CI run — 8 failures, 1 mine

The workflow ran and did the job it was added for. Of 1875 tests, 1867 passed.

**Caused by this work (1):**

- `test_wp_sso.py::test_developer_maps_to_editor` — I had added `wp_login` to
  `WebsiteViewSet.action_roles` as manager-only. It already carries its own,
  finer gate: `_WP_ROLE_MAP` translates the caller's team role into a WordPress
  role and refuses anyone it cannot map, so a developer gets an `editor` login
  and a viewer gets 403. The blanket rule did not tighten that, it contradicted
  it. Removed.

**Pre-existing, red in `main` before any of this (7).** In every case the code
matches its documented design and the test predates the change:

- `test_models.py::test_role_choices` — asserts the role set without
  `seo_executive`, which the model has had for some time.
- `test_ingest_flap.py` ×3 — `ScriptChange` descriptions carry the tag id
  (`identity_label`) so four GA4 properties read as four tags rather than one
  event logged four times. The expected strings predate that.
- `test_normalize.py::test_experiment_list_is_volatile` — asserts `domain=` and
  `r=` survive on `connect.facebook.net`. They deliberately do not any more:
  the host moved into `_IDENTITY_PARAMS` with an empty set, because keeping
  `r=` split one pixel across three rows and fabricated a "Meta Pixel URL
  changed" every couple of days. Renamed and extended to pin the real rule.
- `test_wp_snippet_hooks.py[wp_trash_post]` — the snippet does not register
  that hook and should not: `transition_post_status` already records
  `post_trashed` when the new status is `trash`, so adding it would double-log
  every trash *and* cost a re-paste on every client site.
- `test_recipients_migration.py` — genuinely broken rather than stale. It
  rewound `scripts` to 0025 believing only that app was affected; the executor
  plans against the whole graph, so `websites/0016` (which adds
  `snippet_status`) was unapplied too and the live `Website` model could no
  longer insert. It also never migrated back, leaving the schema short for
  whatever ran next. Now uses historical models throughout and restores the
  graph's leaf nodes in a `finally`.

The point worth keeping: seven of these had been failing for an unknown length
of time, and the only reason anyone knows is that something finally ran them.

## Second CI run — and why the migration test is gone

1874 passed, 1 failed: `test_recipients_migration` again, for a *different*
reason than the first time. That difference is the argument.

Rewinding `scripts` to 0025 produces a **hybrid** schema. The executor unapplies
whatever the dependency graph requires to reach that node, which is not "one
app": `websites/0016` came off (so `snippet_status` was gone, breaking the live
`Website` model — run one) while the `accounts` migration adding
`clickup_list_id` stayed on (so the historical `Team` model omitted a NOT NULL
column — run two). Neither all-live nor all-historical models can be right,
because the database is neither. Which side each model needs flips every time
somebody adds a migration with a cross-app dependency.

Removed rather than fixed a third time:

- **It cannot catch a regression.** It asserts that `scripts/0026` moved
  `recipient_email` into `recipients`. That migration ran in production long
  ago and migrations are immutable — there is no future change for it to guard.
- **The invariant it protects is already covered, against code that does
  change.** `tests/scripts/test_recipients.py::test_all_three_keys_are_always_present`
  asserts `build_recipients("a@site.com") == {"to": ["a@site.com"], "cc": [],
  "bcc": []}`, and `test_empty_input_is_the_empty_shape` covers the other half —
  the same two assertions, on live code.
- **Its cost is recurring and lands on unrelated work.** It mutates global
  schema state mid-suite, so it breaks on migrations that have nothing to do
  with it, and it breaks *other* tests if it fails before restoring.

If a future data migration needs this kind of coverage, the durable pattern is
to put the transformation in a plain function, test the function, and have the
migration call it — not to rewind the graph underneath a running suite.
