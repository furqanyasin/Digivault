# Stacks Monitor SRS — Part 2 (Chapters 17–28)

**Continues from** [`srs.md`](srs.md). Conventions, definitions
and cross-cutting mechanisms are defined there and are not repeated.

---

## Table of contents

17. [Site health](#17-site-health)
18. [Status pages](#18-status-pages)
19. [Client reports](#19-client-reports)
20. [Activity log](#20-activity-log)
21. [Dashboard chatbot](#21-dashboard-chatbot)
22. [Credential vault](#22-credential-vault)
23. [Chrome extension](#23-chrome-extension)
24. [Frontend specification](#24-frontend-specification)
25. [Scheduled jobs and background processing](#25-scheduled-jobs-and-background-processing)
26. [Data retention](#26-data-retention)
27. [Non-functional requirements](#27-non-functional-requirements)
28. [Deployment, operations and testing](#28-deployment-operations-and-testing)
    - [Appendix A — Complete API catalogue](#appendix-a--complete-api-catalogue)
    - [Appendix B — Complete model inventory](#appendix-b--complete-model-inventory)
    - [Appendix C — Environment variables](#appendix-c--environment-variables)

---

## 17. Site health

The `site_health` app covers five independent surfaces that share one concern: is the
site itself (as opposed to its third-party tags) in good shape?

### 17.1 PHP error capture

`PhpError` — `level` (fatal / error / warning / notice / deprecated / info, indexed),
`message`, `file`, `line`, `url`, `raw`, indexed `captured_at`. Indexed
`(website, -captured_at)`.

`POST /api/php-errors/` is public and authenticated **only by `site_id`**, with the
same origin-binding check as `/api/ingest/`: since `site_id` is public (it is embedded
in page HTML), the origin check is what stops a third party injecting fabricated PHP
errors. It accepts a batch (`{site_id, errors: [...]}`) and returns
`{accepted: <n>}` with **202**.

The producer is the WordPress PHP snippet the customer installs alongside the
tracking script.

`GET /api/v1/websites/<id>/php-errors/` lists them. PHP errors feed the security
sub-score (capped at 10 points) and the report's security section.

### 17.2 Site events

`SiteEvent` is a timeline of things that happened to the site. `event_type` covers
manual and integration entries (`plugin_updated`, `plugin_installed`,
`plugin_removed`, `theme_changed`, `core_updated`, `deployment`, `manual`) plus four
SEO-generated types (`seo_noindex_detected`, `seo_robots_block`,
`seo_sitemap_missing`, `seo_meta_changed`). Severity is `info` / `warning` /
`critical`. `occurred_at` defaults to now and is indexed separately from
`created_at`, so a backdated entry sorts correctly.

Endpoints: `GET /api/v1/websites/<id>/events/`,
`POST /api/v1/websites/<id>/events/create/`.

### 17.3 Vulnerability scanning

`VulnerabilityReport` — `component_type` (plugin / theme / core), `component_name`
(indexed), `component_version`, `cve_ids` (JSON), `severity` (indexed), `title`,
`description`, `fixed_in_version`, `source`, `references`. Unique
`(website, component_name, title)`, ordered by severity then component name.

`SiteScanState` is one-per-website: `last_scanned_at`, `scan_status`
(never / running / done / failed), `wp_version`, `wp_latest_version`,
`wp_update_available`, `plugins_detected` (JSON), `error`.

`site_health.run_security_scan(website_id)`:

1. Sets `scan_status = "running"`.
2. Collects distinct non-empty `wp_plugin` values from the site's active `Script`
   rows — the plugin inventory is inferred **from script URLs**, not from any
   privileged WordPress access.
3. **With `WPSCAN_API_KEY`:** queries `wpscan.com/api/v3/plugins/<slug>` per plugin
   and `wordpresses/<version>` for core, mapping CVSS to severity
   (≥ 9.0 critical, ≥ 7.0 high, ≥ 4.0 medium, else low; unparseable → medium).
   Slugs are best-effort (`"Yoast SEO"` → `yoast-seo`), so matching is imperfect.
4. **Without a key:** falls back to `_heuristic_scan()`, a curated list of ten
   historically risky plugin patterns (`file-manager` and `wp-file-manager` — RCE
   history, `revslider` / `revolution-slider` — critical CVEs, `wp-super-cache`,
   `contact-form-7`, `woocommerce`, `elementor`, `wpforms`, `ninja-forms`). Each
   result names the missing API key in its description so the user knows the finding
   is a pattern match, not a CVE lookup.
5. Deletes prior results for the website and inserts the fresh set, so findings never
   accumulate stale rows.
6. Compares the detected core version against `api.wordpress.org/core/version-check/1.7/`
   to set `wp_latest_version` and `wp_update_available` via a digit-only tuple compare.
7. Sets `scan_status = "done"`, then recalculates health.

Any exception sets `scan_status = "failed"` with the error text — the failure is
visible in the UI rather than silent.

Endpoints: `GET /api/v1/websites/<id>/vulnerabilities/`,
`POST /api/v1/websites/<id>/scan/`.

### 17.4 SEO health

`SeoReport` is one-per-website and cumulative:

| Group | Fields |
|---|---|
| Run state | `last_checked_at`, `check_status` (never/running/done/failed), `error` |
| robots.txt | `robots_status` (found/missing/error), `robots_blocks_all`, `robots_content` (raw, truncated 20 000 chars) |
| Sitemap | `sitemap_status`, `sitemap_url`, `sitemap_url_count`, `sitemap_pages` (same-origin URLs, capped 1000) |
| Indexability | `homepage_indexable`, `pages_checked` (cumulative `[{url, indexable, reason, checked_at}]`), `noindex_count`, `scan_cursor` |
| On-page | `meta_title`, `meta_description`, `h1`, `canonical_url`, `schema_types` |

**Checkers** ([apps/site_health/seo_checker.py](../apps/site_health/seo_checker.py))
are pure except `fetch()`, which enforces `assert_public_url()`, sends browser-like
headers, reads at most 2 MB and lowercases response header names.

- `parse_robots(text)` — strips `#` comments, groups directives by user-agent, and
  reports `blocks_all` only when the `*` group has `Disallow: /` **and no**
  `Allow: /`. Collects every `Sitemap:` line.
- `count_sitemap_urls(xml)` — follows a `<sitemapindex>` **one level deep**, bounded
  to the first 10 child sitemaps, and returns `(count, urls)`. A parse error returns
  `(0, [])` rather than raising.
- `page_indexability(html, x_robots_tag)` — `X-Robots-Tag: noindex` wins, then a
  `<meta name="robots">` containing `noindex`. Returns `(bool, reason)`.
- `parse_homepage_meta(html)` — title, meta description, first H1, canonical URL and
  the set of schema.org `@type` values found in JSON-LD.

**The rotating window is the key design decision.** The page universe is the homepage
plus pages the *snippet has actually observed* plus sitemap pages. Snippet-observed
pages matter because that is where a hidden `noindex` turns up — noindex pages are
deliberately kept out of sitemaps. Each run checks the homepage **always**, plus a
rotating window of `MAX_PAGES - 1 = 14` other pages selected from `scan_cursor`
(wrapping around), then **merges** results into `pages_checked` and drops entries no
longer in the universe. Over a few daily runs every page is covered without one heavy
scan.

**Regression alerts** are skipped entirely on the first-ever run (`check_status ==
"never"`), so onboarding a site never fires a false alarm. Thereafter:

| Transition | SiteEvent | Severity |
|---|---|---|
| Homepage `indexable: true → false` | `seo_noindex_detected` | critical |
| `robots_blocks_all: false → true` | `seo_robots_block` | critical |
| Sitemap `found → missing` | `seo_sitemap_missing` | warning |
| Title / description / H1 / canonical / schema types changed | `seo_meta_changed` | warning |

Meta-change detection only compares fields that have **ever** been populated, which
skips the transition from a never-captured blank to a first value. Each alert also
calls `notify_team()`, which routes through `resolve_channels(website)`.

`site_health.run_due_seo_checks` runs daily at **04:00 UTC** and enqueues a check for
every website whose `seo_scan_interval_days` is non-zero and whose last check is older
than that interval (or has never run).

Endpoint: `GET /api/v1/websites/<id>/seo/` (and a POST to trigger).

### 17.5 HTTP security headers

`grade_headers(headers)`
([apps/site_health/header_checker.py](../apps/site_health/header_checker.py)) is pure
and network-free. Seven checks, weights summing to 100, each returning
`pass` / `warn` / `fail`. A `warn` earns **half** the weight — the header is present
but weaker than recommended.

| Header | Weight | `warn` conditions |
|---|---|---|
| `Strict-Transport-Security` | 25 | `max-age < 15552000` (180 d), or missing `includeSubDomains` |
| `Content-Security-Policy` | 25 | contains `unsafe-inline`/`unsafe-eval`, or has neither `default-src` nor `script-src` |
| `X-Frame-Options` | 15 | value is not `DENY`, `SAMEORIGIN` or `ALLOW-FROM…` |
| `X-Content-Type-Options` | 10 | value is not exactly `nosniff` |
| `Referrer-Policy` | 10 | value is `unsafe-url` or `no-referrer-when-downgrade` |
| `Permissions-Policy` | 10 | — (present = pass) |
| `Cross-Origin-Opener-Policy` | 5 | absent → **warn** (not fail); or value is not `same-origin`/`same-origin-allow-popups` |

Score = `round(100 × earned / total)`. Grade bands: **A+** ≥ 95, **A** ≥ 85,
**B** ≥ 70, **C** ≥ 55, **D** ≥ 40, else **F**. Every check returns a concrete
remediation string, stored alongside so the UI never shows a bare failure.

`SecurityHeaderReport` stores `final_url`, `status_code`, `score`, `grade`, the full
`headers` array, and pass/warn/fail counts.

Task: `site_health.run_security_header_check(website_id)`.
Endpoint: `GET /api/v1/websites/<id>/security-headers/` (and a POST to trigger).

---

## 18. Status pages

### 18.1 Models

`StatusPage` — team-scoped, `name`, **globally unique** `slug`, `description`,
`allow_indexing` (**default `False`** — search engines are excluded unless the user
opts in), `logo_url`, `brand_color` (hex).

`overall_status` is derived from the statuses of active monitors on the page: any
`down` → `outage`; any `degraded` → `degraded`; otherwise (including no monitors at
all) → `operational`.

`StatusPageMonitor` — unique `(status_page, monitor)`, optional `display_name`
override and `display_order`.

`StatusPageIncident` — `title`, `body`, `status` (investigating → identified →
monitoring → resolved). `save()` maintains `resolved_at` as a strict function of
status: set on transition to `resolved`, and **cleared** whenever status is anything
else, so reopening an incident cannot leave a stale resolution timestamp.

`MaintenanceWindow` — `title`, `message`, `scheduled_start`, `scheduled_end`, with an
`is_active` property true only inside the window.

### 18.2 Uptime bars

`StatusPageMonitor.uptime_bars(days=90)` returns one entry per day, oldest first:

- `no-data` when the day had zero checks — distinct from "up", so gaps read honestly.
- `down` if any check that day was down, else `degraded` if any was degraded, else `up`.
- `down_minutes` / `degraded_minutes` approximated as
  `failed_checks × (check_interval / 60)`, since each failed check covers roughly one
  interval. This powers the bar tooltip.

### 18.3 Endpoints

| Method | Path | Auth |
|---|---|---|
| GET/POST | `/api/v1/status-pages/` | Team |
| GET/PATCH/DELETE | `/api/v1/status-pages/<pk>/` | Team |
| GET/POST | `/api/v1/status-pages/<pk>/monitors/` | Team |
| GET/PATCH/DELETE | `/api/v1/status-pages/<pk>/monitors/<entry_pk>/` | Team |
| GET/POST | `/api/v1/status-pages/<pk>/incidents/` | Team |
| GET/PATCH/DELETE | `/api/v1/status-pages/<pk>/incidents/<pk>/` | Team |
| GET/POST | `/api/v1/status-pages/<pk>/maintenance/` | Team |
| GET/PATCH/DELETE | `/api/v1/status-pages/<pk>/maintenance/<pk>/` | Team |
| GET | `/api/v1/public/status/<slug>/` | **None** |

A `_PageScopedChildMixin` ensures every child route resolves its parent page within
the caller's team before touching incidents, maintenance or monitor entries.

The public endpoint sets `permission_classes = []` and
`authentication_classes = []`, prefetches monitors, incidents and maintenance
windows in one go, and returns the page with monitors (including 90-day uptime bars),
incidents and maintenance. Incident and maintenance operations are audited
(`INCIDENT_POSTED`, `INCIDENT_UPDATED`, `INCIDENT_DELETED`,
`MAINTENANCE_SCHEDULED`, `MAINTENANCE_DELETED`).

---

## 19. Client reports

### 19.1 Model

`Report` — `team`, `website`, `period_start`, `period_end`, `report_format`
(pdf / csv), `sections` (JSON; **empty means all**), `status`
(pending / done / failed), `file` (`upload_to="reports/"`), `error`, `generated_at`.
Indexed `(team, -created_at)`.

Seven toggleable sections in `SECTION_KEYS` — `active_scripts`, `script_changes`,
`performance`, `uptime`, `security`, `domain_ssl`, `recommendations`. An
**overview is always included** and is not a toggle.

### 19.2 Data gathering

`ReportBuilder.gather(website, start, end, sections)` **skips the queries for
excluded sections entirely** rather than gathering everything and filtering at render
time.

| Section | Content |
|---|---|
| Overview (always) | Website name, domain, platform, status, health score; period |
| `active_scripts` | Active scripts **grouped by source domain** with a file count, excluding Stacks Monitor's own infra so it matches the website detail "Active Scripts" list. Sorted with unknown providers first — they are what needs attention |
| `script_changes` | Counts by change type in the window, plus the 20 most recent critical/high descriptions |
| `domain_ssl` | Registrar, hosting provider, domain days, SSL days |
| `uptime` | Per monitor: name, URL, current status, uptime %, total checks, down checks, computed over the window from raw `MonitorCheck` rows |
| `performance` | Latest mobile and desktop score + LCP |
| `security` | Vulnerability counts by severity; PHP errors in the window |
| `recommendations` | Derived (below) |

`_recommendations()` produces plain-language actions: domain or SSL expiring within
30 days (with the day count), critical vulnerabilities ("patch immediately"), high
vulnerabilities to review, and the count of high-risk script changes needing review.
When nothing fires it returns the single line "No urgent issues detected this
period." — so the section is never blank.

### 19.3 Rendering and delivery

`render_csv(data)` emits a flat CSV. `render_pdf(data)` uses ReportLab with a custom
`_ReportCanvas` subclass that draws page furniture (header/footer, page N of M via a
two-pass save) and a `_BookmarkDoc` `SimpleDocTemplate` subclass whose
`afterFlowable` registers PDF outline bookmarks per section.

`generate_report()` ([apps/reports/services.py](../apps/reports/services.py)) creates
the row `PENDING`, renders, saves the file as
`<domain>_<start>_<end>.<ext>` (slashes replaced), and sets `DONE` +
`generated_at`. On any exception it records `FAILED` with a 1000-char `error` and
**returns the report rather than raising**, so the caller always gets a row it can
show the user.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/reports/` | Team-scoped list |
| POST | `/api/v1/reports/generate/` | **Synchronous.** 201 when `DONE`, 500 when `FAILED`. Audited as `REPORT_GENERATED` with `site_meta` |
| GET | `/api/v1/reports/<pk>/download/` | `FileResponse` as attachment; 404 unless `DONE` with a file |
| DELETE | `/api/v1/reports/<pk>/` | Deletes the stored file too; audited |

`reports.generate_monthly` runs on the **1st of each month at 04:00 UTC** and produces
a PDF covering the previous calendar month for every `active` website.
`reports.generate_for_website(website_id, start, end, fmt)` exists for asynchronous
one-offs.

---

## 20. Activity log

### 20.1 Model

`ActivityLog` — `team`, nullable `actor` (SET_NULL, so a deleted user's history
survives as "system"), `action` (indexed choice), `resource_type`, `resource_id`
(free-text, so it can hold non-UUIDs), `description` (300 chars), `ip_address`,
`metadata` (JSON). Indexed `(team, -created_at)` and `(actor, -created_at)`.

`Action` enumerates **60 action types** across auth (login, logout, failed login, 2FA
enable/disable/setup-started, backup-code regeneration), credentials
(created / revealed / updated / deleted / shared / unshared), websites
(created / updated / deleted / scan triggered / snippet verified / snippet
regenerated / change acknowledged / WP login / WP SSO secret rotated), scripts
(reviewed), monitors (created / updated / deleted / paused / resumed / rule created /
rule deleted), reports, status pages and incidents/maintenance, team membership,
settings, clients (created / updated / status changed / synced / imported / exported),
alerts (rule and channel lifecycle), domains and performance.

### 20.2 Role-aware scoping

`_scoped_logs(request)` is the security boundary: **managers and owners see the whole
team** (optionally narrowed by `?user_id=`), while **everyone else sees only their own
activity**. This is why the Activity Log page is manager-only in the sidebar yet the
dashboard "Recent activity" card and each website's activity tab still work for
developers — the backend scoping holds regardless of which UI surface asks.

### 20.3 Filters

`_apply_filters()` supports:

| Param | Behaviour |
|---|---|
| `action` | Exact match |
| `actions` | Comma-separated set — a named view like "approvals" spans several action types, which a single `action` cannot express. Empty values are ignored so a stray `?actions=` doesn't silently return nothing |
| `resource_type` | Exact match |
| `website_id` | Matches `resource_id` **or** `metadata.website_id`, because site-scoped actions carry the ID either way (script reviews and change acknowledgements use metadata) |
| `client_id` | Logs carry no client reference, so a client's activity is defined as actions on the client record itself **plus** everything on the sites it owns |
| `start`, `end` | `created_at` range |
| `q` | `description__icontains` |
| `user_id` | Managers only |

`_valid_uuids()` filters out malformed values before any `id__in` lookup, because
`resource_id` is a free-text column and a non-UUID would make the query raise.

`_resource_names(rows)` bulk-resolves website and client names for one page in **two
queries regardless of page size** — a `SerializerMethodField` doing its own lookup
would be one query per row. `list()` is overridden rather than using
`get_serializer_context()` because the names can only be looked up once the page is
known.

### 20.4 Endpoints

- `GET /api/v1/logs/` — paginated, filtered, with resolved names.
- `GET /api/v1/logs/export/` — CSV (`created_at`, `actor_email`, `action`,
  `resource_type`, `resource_id`, `description`, `ip_address`), streamed with
  `.iterator()`, honouring the same filters and scoping.

`audit.purge_old_logs` runs Sundays at 03:30 UTC, deleting rows older than 90 days in
500-row chunks.

---

## 21. Dashboard chatbot

`POST /api/v1/chat/` — authenticated, `{message}` → `{reply, type, data}`.

It is **deterministic regex intent matching**, not an LLM. No external AI service is
called and no message content leaves the server.
[apps/chat/intents.py](../apps/chat/intents.py) `detect_intent()` returns an intent
plus params; `process_message(team, message)` dispatches to one of seventeen handlers,
all scoped to the caller's team.

Ordering in `detect_intent` is deliberate — the more specific patterns are tested
first, and a bare domain mention falls through to `check_website`:

| Intent | Trigger (abridged) |
|---|---|
| `help` | help, commands, "what can you", options, guide |
| `summary` | summary, overview, dashboard, stats |
| `onboard_website` | a domain **plus** onboard / add / register / new site / setup |
| `website_scripts` | a domain **plus** scripts / third-party / trackers / tags / pixels |
| `check_website` | a domain plus check/status/details/info/show/how is/forms — **or a bare domain** |
| `check_client` / `list_clients` | clients / customers, with or without a detail verb |
| `monitors_down` / `list_monitors` | "monitors down" etc. / monitors, uptime |
| `high_alerts` | high/critical/urgent **plus** alerts/changes/issues/risks |
| `list_alerts` | alerts, notifications, unread, pending changes |
| `list_changes` | recent/latest/last **plus** changes/updates, or "script changes" |
| `unknown_scripts` | unknown/unidentified/unclassified/suspicious **plus** scripts/trackers/tags |
| `list_scripts`, `list_forms`, `list_websites` | the plain nouns |
| `fallback` | anything else — returns guidance rather than an error |

A user with no active team gets an explanatory reply (`type: "no_team"`) instead of an
error. The frontend surface is `ChatWidget`, mounted in the dashboard layout.

---

## 22. Credential vault

### 22.1 Encryption

[apps/credentials/encryption.py](../apps/credentials/encryption.py) wraps Fernet
(AES-128-CBC + HMAC-SHA256 under a 256-bit key) via **`MultiFernet`** so key rotation
is possible:

- `VAULT_ENCRYPTION_KEYS` — ordered comma-separated list. The **first** key encrypts
  new data; **all** keys are tried on decrypt.
- `VAULT_ENCRYPTION_KEY` — legacy single key, still honoured when the list is unset,
  so existing deployments keep working.
- No key configured → `ValueError` naming both variables.

`encrypt()`, `decrypt()`, `rotate_token()` (re-encrypt under the current primary) and
`rotate_key(old, new, ct)` (retained for backward compatibility) are the only entry
points. Keys live **exclusively in environment variables** — never in the database or
logs. `decrypt()` raises `InvalidToken` on tampering or key mismatch, and callers must
catch it and treat it as a vault integrity error.

**Rotation procedure** (`docs/runbooks/key-rotation.md`): prepend a new key to
`VAULT_ENCRYPTION_KEYS`, deploy, run
`python manage.py rotate_vault_keys` to re-encrypt every blob under the new primary,
then drop the old key.

The same module encrypts `User.totp_secret` and `Team._clickup_api_token`.

### 22.2 `Credential`

Sixteen types: `wordpress`, `cpanel`, `godaddy`, `namecheap`, `hostinger`,
`cloudflare`, `ftp`, `wix`, `webflow`, `framer`, `shopify`, `siteground`,
`bluehost`, `wpengine`, `kinsta`, `custom`.

`team` (CASCADE) is mandatory; `website` (SET_NULL, nullable) is optional so
standalone hosting and registrar logins can exist without a site. `label`,
`credential_type`, `login_url`, `created_by`.

Three encrypted `BinaryField`s — `_username`, `_password`, `_notes`. The column type
itself signals to any operator browsing the database that these are ciphertext blobs,
not readable strings. `username_hash` is a SHA-256 of the username, so duplicate
lookup needs **no decryption**.

Password health is computed **at set time** so strength never requires decryption:
`score_password_strength()` returns 0–4 from length ≥ 8, length ≥ 12, mixed case,
a digit, and a non-alphanumeric (capped at 4). `set_password()` also stamps
`last_password_changed_at`; a `password_age_days` property exposes ageing.

### 22.3 Visibility and permissions

Three overlapping mechanisms, each answering a different question.

**`CredentialQuerySet.visible_to(user)`** — which credentials appear in a list:
everything in teams where the user is owner or manager, **plus** anything they
created, **plus** anything explicitly shared with them.

**`can_view_credential` / `can_modify_credential`**
([apps/credentials/permissions.py](../apps/credentials/permissions.py)) — view
follows the same three-way rule; **modify** (edit / delete / share / unshare) is
owner, manager or creator only. A developer with a share **cannot** modify.

**`CredentialService._REVEAL_ROLES`** — who may decrypt at all: owner, manager,
developer, editor, seo. **`viewer` is excluded** and gets an explicit
`ForbiddenError` telling them to contact their team manager.

`CredentialShare` — unique `(credential, user)`, with `shared_by` and a
`can_view_password` flag. When false, the recipient can *use* the credential (the
extension still autofills it) but the dashboard never shows them the plaintext.
Owners, managers and the creator need no share row — their access is implicit.

### 22.4 Reveal and audit

`CredentialService.reveal(credential, user, ip, for_autofill=False)`:

1. `_assert_can_reveal()` — team membership, then role check.
2. Writes a `CredentialAccessLog` row **unconditionally, before returning any
   plaintext**.
3. Decrypts username, password and notes.
4. If the requester may not view the password (a share with
   `can_view_password=False`) **and** this is not an autofill request, the password
   is blanked and `password_hidden: true` is returned. Autofill still receives it so
   the extension can fill the login form.

`CredentialAccessLog` — `credential`, `user`, `action` (`viewed`,
`copied_password`, `edited`), `ip_address`, indexed `(credential, -created_at)`. Its
docstring states the operational rule: **application code must never UPDATE or DELETE
these rows**, and in production the app's DB user should hold only INSERT on this
table.

### 22.5 Import

`POST /api/v1/credentials/import/` accepts a **LastPass CSV export**
(`url, username, password, totp, extra, name, grouping, fav`), max 5 MB, decoded as
`utf-8-sig`. Per row:

- Rows with neither username nor password (secure notes) are **skipped**.
- `extra` becomes notes; a `totp` value is appended as `TOTP secret: …`.
- The URL's host is matched against team websites (exact, bare, `www.`) to link the
  credential; unmatched rows become standalone "Hosting & General" logins.
- `credential_type` is guessed from URL + grouping via `_LP_TYPE_HINTS`.
- Re-importing the same `(website, username_hash)` **refreshes the password** rather
  than duplicating.

Returns `{created, updated, skipped}` and writes one audit row summarising the batch.

### 22.6 Endpoints

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/api/v1/credentials/` | Team-wide vault (visibility-filtered) |
| POST | `/api/v1/credentials/import/` | LastPass CSV |
| GET/POST | `/api/v1/websites/<id>/credentials/` | Per-website |
| GET/PATCH/DELETE | `/api/v1/credentials/<pk>/` | Modify gated by `can_modify_credential` |
| POST | `/api/v1/credentials/<pk>/reveal/` | Decrypts; always audited |
| GET | `/api/v1/websites/<id>/credential-audit/` | Access log for a site's credentials |
| POST | `/api/v1/websites/<id>/credentials/share/` | Bulk-share a site's credentials |
| GET/POST | `/api/v1/credentials/<pk>/shares/` | List / grant |
| DELETE | `/api/v1/credentials/<pk>/shares/<user_id>/` | Revoke |
| GET | `/api/extension/credentials/?domain=…` | Metadata only, never plaintext |
| POST | `/api/extension/credentials/save/` | Capture from the extension's save prompt |

`ExtensionCredentialLookupView` with no `domain` (or `?all=1`) returns the **entire
visible vault** newest-first, backing the extension's "All items" tab. With a domain
it matches the website's domain (with and without `www.`) **or** any credential whose
`login_url` contains `//<host>` — anchoring on `//` keeps it from matching the host
inside a path, and this is what lets a standalone cPanel login surface on the right
site.

`ExtensionCredentialSaveView` (`CredentialSaveThrottle`) requires an existing team
website for the domain and returns `website_not_found` with actionable text if there
isn't one; otherwise it updates by `username_hash` or creates
`"<domain> login"`.

---

## 23. Chrome extension

Manifest V3. Permissions: `activeTab`, `storage`, `scripting`, host permissions
`<all_urls>`. Content script runs at `document_idle`.

### 23.1 Background service worker

[extension/background.js](../extension/background.js) — the only component that holds
tokens, in `chrome.storage.local`. `getApiBase()` reads `serverUrl` from
`chrome.storage.sync`, defaulting to `https://stacksmonitor.com`.

`authedFetch()` retries once through `tryRefreshToken()` on a 401 and clears
`access` / `refresh` / `email` when refresh fails, so an expired session logs out
cleanly rather than looping.

On `chrome.tabs.onUpdated` it calls `GET /api/extension/lookup/?domain=<host>` and
badges the tab with the script count — **green** normally, **orange
(`#f97316`)** when `has_unknown` is true. Results are cached in
`chrome.storage.session` keyed by tab ID and removed on `onRemoved`.

MV3's `chrome.action.*` promises reject when a tab has closed mid-flight, so every
call is wrapped in `actionSafe()` / `setBadgeSafe()` — a closed tab must not surface
as an extension error.

Message handlers cover credential lookup, login (`POST /api/extension/token/`),
logout, and reading/clearing `dv_pending_autofill` — content scripts cannot read
`chrome.storage.session` directly, so the worker brokers it.

### 23.2 Content script

[extension/content.js](../extension/content.js) does four things, all inside a
**Shadow DOM root** (`getOrCreateShadowRoot`) so injected UI cannot be styled or
scraped by the host page.

1. **Autofill.** `findLoginPairs()` locates each visible `input[type=password]` and
   `findUsernameField()` walks candidate inputs to pair it. An icon button is
   injected and positioned against the field; clicking opens a dropdown of matching
   credentials with full keyboard navigation. `fillField()` sets the value and
   dispatches events so framework-bound inputs register the change.
2. **Save prompt.** `attachSaveCapture()` records submitted credentials; after
   navigation `checkPendingSave()` shows a save bar offering to store them via
   `/api/extension/credentials/save/`, rendering the API's error text inline (e.g.
   "add the website first") rather than failing silently.
3. **Script reporting.** Only when the page already carries a
   `script[data-site]` snippet tag — it collects `script[src]` entries and POSTs to
   `/api/ingest/`. It never reports on sites that have not opted in, and it reports
   **scripts only**, never forms.
4. **Portal handoff.** `maybeHandoff()` implements the extension side of §6.6.

`safeSendMessage()` swallows `chrome.runtime.lastError`, which fires routinely when
the service worker is asleep.

### 23.3 Popup and options

`popup.html/js` — login form, the current tab's script summary, a credential list for
the domain, an "All items" tab (the no-domain lookup) with an **Open** button that
navigates to any stored `login_url`, and logout.

`options.html/js` — sets `serverUrl` in `chrome.storage.sync` for self-hosted or
staging backends.

---

## 24. Frontend specification

### 24.1 Stack

Next.js 16.2.6 App Router, React 19.2.4, TypeScript 5, Tailwind v4 (via
`@tailwindcss/postcss`). UI primitives are Radix (`avatar`, `checkbox`, `dialog`,
`dropdown-menu`, `label`, `select`, `separator`, `slot`, `tabs`, `toast`) wrapped in
local `components/ui/*` with `class-variance-authority`, `clsx` and `tailwind-merge`.
State: `@tanstack/react-query` v5 and `zustand` v5. Charts: `recharts` v3,
`chart.js` + `react-chartjs-2`, `countup.js`. Also `next-themes`, `js-cookie`,
`sweetalert2`, `flatpickr`, `choices.js`, `lucide-react`.

### 24.2 Auth and the BFF pattern

Tokens live **only** in HttpOnly cookies (`ss_access`, `ss_refresh`,
`ss_2fa_device`), set by Next.js route handlers. Two access paths exist:

- **Server components** call `getAccessToken()`
  ([frontend/src/lib/server-token.ts](../frontend/src/lib/server-token.ts)) — an
  `await cookies()` read — and pass the token into `api.get()`, which talks to Django
  directly over the internal network.
- **Client components** call a Next.js `/api/*` route handler, which reads the cookie
  server-side and forwards. The browser therefore never sees a JWT.

`frontend/src/proxy.ts` guards every request. `PUBLIC_PATHS` are `/login`,
`/register`, `/forgot-password`, `/reset-password`, `/2fa/`, `/status/`,
`/api/auth`, `/api/public` and `/api/password-reset` — the last is public at the proxy
layer because the anonymous forgot/reset pages call it, and its authenticated
sub-routes each enforce the token themselves.

When `ss_access` is missing but `ss_refresh` exists, the proxy performs a **silent
refresh**. Two details in that path are load-bearing:

1. It calls `request.cookies.set("ss_access", newAccess)` and returns
   `NextResponse.next({ request })` so **this render's** server components see the new
   token. Without it, the page that triggered the refresh still reads the missing
   cookie, every token-backed fetch 401s, and the page renders empty until a manual
   reload.
2. Refresh-token rotation returns a **new refresh token**, which must be persisted or
   the next refresh fails against the rotated old one.

Failure behaviour differs by path: `/api/*` returns JSON 401 so client callers degrade
gracefully; page routes redirect to `/login?next=<pathname>`. The matcher excludes
`_next/static`, `_next/image`, `favicon.ico` and `api/s.js`.

### 24.3 API client

[frontend/src/lib/api.ts](../frontend/src/lib/api.ts) unwraps the envelope
(`envelope.data ?? envelope`), throws a typed `ApiError(status, data)` on non-2xx, and
returns `undefined` for 204.

`api.getAll()` is the paginated variant described in §4.4 and must be used for any
list that can exceed 25 rows. The file also declares ~40 exported TypeScript
interfaces mirroring the serializers; several carry comments recording bugs the type
prevented, e.g. `Notification.delivery_status` (there is no `status` field — reading
one silently rendered a blank cell) and `Script.suspicion_reasons` ("advisory — must
be shown with the flag").

### 24.4 Route map

**Public**

| Route | Purpose |
|---|---|
| `/` | Landing / redirect |
| `/status/[slug]` | Public status page (auto-refreshing) |
| `/invite/[token]` | Accept a team invitation |

**Auth group** — `/login`, `/register`, `/forgot-password`, `/reset-password`,
`/first-password` (admin-created users), `/2fa/setup`, `/auth/extension` (handoff
landing).

**Dashboard group** — all behind the proxy, wrapped by `(dashboard)/layout.tsx`:

| Route | Purpose |
|---|---|
| `/dashboard` | Fleet overview (see §24.6) |
| `/clients`, `/clients/new`, `/clients/[id]` | Client management, CSV import/export |
| `/websites`, `/websites/new`, `/websites/[id]` | Website list and the 14-tab detail page |
| `/credentials` | Vault |
| `/alerts` | Alert rules, feed and delivery history |
| `/renewals` | Renewal Center (manager-only) |
| `/logs` | Activity Log (manager-only) |
| `/team` | Members, invitations, roles, feature access |
| `/settings` | Profile, 2FA, and the team half for managers |
| `/account` | Merged into Settings; route retained |
| `/heatmap` | Uptime heatmap across the fleet |
| `/monitors`, `/monitors/new`, `/monitors/[id]`, `/monitors/channels` | Kept routable for deep links after monitors moved into the website Uptime tab |
| `/status-pages`, `/status-pages/[id]` | Kept routable after status pages left the sidebar |

### 24.5 Layout and navigation gating

`(dashboard)/layout.tsx` is a server component. It fetches `/auth/me/` and
`/auth/teams/` in parallel, resolves the active team, and derives `isOwner`,
`isManager` and `myFeatures`.

Nav filtering rules, in order: `always: true` items are shown to everyone
(Dashboard, Heatmap, Settings); `managerOnly` items are hidden from non-managers;
owners then see everything; `feature`-keyed items require the key in `myFeatures`;
anything else is shown. Icons cannot cross the RSC boundary as props, so the layout
passes **string keys** which `NavLinks` maps to `lucide-react` components.

The sidebar is `sticky top-0 h-screen` with its own scroll, holding the logo, team
switcher, global search, notification bell, nav, theme toggle and logout. Main content
uses `flex-1 min-w-0` so wide tables stay contained instead of forcing page-wide
overflow, plus bottom padding for the chat widget's safe area.

`FeatureGuard` renders for non-owners as a client-side enforcement companion to the
server-side scoping. `ChatWidget` and `ExtensionAuthBridge` mount once per session.

### 24.6 Dashboard composition

`getData()` issues **twelve** requests through `Promise.allSettled`, so one failure
degrades one card rather than the page. Each is individually justified in the source:

- `getAll` for websites, monitors, changes, clients and credentials — a plain `get`
  silently dropped everything past the first 25 rows and under-reported how many
  monitors were down.
- A single `?days=90` uptime-trend fetch, with the trend cards slicing it
  **client-side**, so a preset click costs nothing. Previously each click refetched
  ten endpoints.
- `/auth/teams/` for the member count, because it already carries `member_count` per
  team — this replaced a sequential `/auth/me/` then that team's members, two round
  trips in series after the parallel batch, on every page load and filter change.

Derived values are computed in `getData`, not during render: `reportingCount` uses
`Date.now()`, which is not idempotent and which React's purity rule rightly rejects
inside a component body.

Stacks Monitor's own infra domains are filtered out of the change list before counting, so
the alert KPI cannot disagree with the Change Log, and severity composition is derived
from the same filtered list the KPI counts.

Cards: fleet health donut, renewal urgency bars, uptime card, fleet checks row, setup
checklist, alerts card, VIP sites, needs-attention list and recent activity.

### 24.7 Website detail tabs

`/websites/[id]` renders up to **fourteen** tabs, three conditionally:

| Tab | Content |
|---|---|
| Overview | Site overview grid, health score with rubric, snippet status |
| Scripts | Inventory with review actions, suspicion flags, per-script timeline |
| Plugins *(if detected)* | `plugins_detected` from `SiteScanState` |
| Forms | Detected forms with fields, detection type, provider, submission counts |
| Uptime & Downtime | Monitors, response chart, uptime bars, sparkline, status-page link |
| Access & Domain | WHOIS, hosting, SSL, hosting renewal, mail/SPF/DKIM/DMARC, credentials, WP login |
| Performance | PSI history, CrUX field data, weekly trends |
| Change Log | Script changes with acknowledge and bulk-acknowledge |
| PHP Errors *(if any)* | Captured PHP errors |
| Site Events *(if any)* | Timeline including SEO regressions |
| Security | Vulnerabilities, security-header grade panel |
| SEO | robots, sitemap, indexability, on-page meta, schema |
| Reports | Generate and download per-website reports |
| Setup | Snippet install instructions, verify, regenerate, WP SSO secret |

A `js-errors` tab content block also exists (`JsErrorsTab`), part of the in-progress
JS-error feature on this branch.

### 24.8 BFF route inventory

**95 `route.ts` handlers** under `frontend/src/app/api/`, grouped:

`auth/` (login, logout, register, refresh, first-password, me, teams, 2FA
setup/confirm/verify/disable/status/regenerate-backup, ext-handoff, ext-tokens) ·
`websites/` (CRUD plus scan, verify-snippet, domain, forms, performance, performance/run,
crux, crux/run, seo, security-headers, vulnerabilities, php-errors, events,
assignments, credentials, credentials/share, scripts/[id]/review, wp-login,
wp-sso-secret, expiring-domains, expiring-ssl, expiring-hosting) · `clients/`
(CRUD, search, import, export, activate, deactivate) · `credentials/` (CRUD, reveal,
import, shares) · `monitors/` (CRUD, checks, pause, resume, check-now,
notification-rules) · `notification-channels/` (CRUD, test) · `status-pages/`
(CRUD, monitors) · `teams/` (members, invitations, invite, users, settings,
clickup-test, switch) · `changes/` (acknowledge, bulk-acknowledge) ·
`alert-rules/`, `notifications/`, `logs/`, `reports/` (list, generate, download,
delete), `password-reset/` (request, confirm, approve, reject),
`invitations/[token]` (view, accept), `public/status/[slug]`, `chat/`.

---

## 25. Scheduled jobs and background processing

### 25.1 Celery configuration

Broker and result backend are both `REDIS_URL`. JSON-only serialization, UTC,
`task_track_started`, and a **300-second hard time limit per task**. Production runs
one worker with `--concurrency=2` and beat with `-s /tmp/celerybeat-schedule`.

### 25.2 Beat schedule

From `CELERY_BEAT_SCHEDULE` in [config/settings/base.py](../config/settings/base.py):

| Task | Schedule (UTC) | Purpose |
|---|---|---|
| `monitors.run_due_checks` | every **30 s** | Queue due uptime checks |
| `common.system_heartbeat` | every **5 min** | Dead-man's-switch ping |
| `alerts.send_digest` (`hourly_digest`) | every hour at `:00` | Hourly digest |
| `monitors.rollup_daily_uptime` | 00:15 | Aggregate yesterday's checks |
| `monitors.purge_old_checks` | 01:00 | Drop raw checks > 35 d |
| `performance.purge_old_reports` | Sun 02:00 | Drop PSI reports > 365 d |
| `site_health.purge_old_php_errors` | Sun 02:30 | Drop PHP errors > 90 d |
| `alerts.purge_old_notifications` | Sun 02:45 | Drop non-pending notifications > 90 d |
| `scripts.purge_old_snapshots` | Sun 03:00 | Drop snapshots > 90 d |
| `audit.purge_old_logs` | Sun 03:30 | Drop activity logs > 90 d |
| `site_health.run_due_seo_checks` | 04:00 | Enqueue due SEO checks |
| `reports.generate_monthly` | 1st of month 04:00 | Previous-month PDF per active site |
| `domains.check_all_domains` | 06:00 | WHOIS / SSL / hosting / mail per site |
| `websites.recalculate_all_health` | 06:30 | Nightly health sweep |

The 06:00 → 06:30 ordering is deliberate: the health sweep scores the **freshest**
expiry data, and gives time-based deductions (expiry windows, reporting gap) a daily
decay.

### 25.3 Event-driven tasks

| Task | Trigger | Retries |
|---|---|---|
| `scripts.process_ingest_payload` | Every ingest POST, and the server-side Scan | 3, 10 s delay |
| `websites.run_initial_checks` | `post_save` on a new Website | 2, 30 s delay |
| `monitors.check_single_monitor` | `run_due_checks`, or Check Now | **0** — a retry would double-count |
| `domains.check_domain` | Daily sweep, or manual refresh | 2, 60 s delay |
| `alerts.deliver_notification` | Immediate-mode rules, and digests | 3, 30 s delay |
| `site_health.run_security_scan` | Scan (+5 s countdown), or manual | — |
| `site_health.run_seo_check` | Scan (+5 s countdown), due sweep, or manual | — |
| `site_health.run_security_header_check` | Manual | — |
| `performance.check_website_performance` | Manual run, or initial checks | 2, 30 s delay |
| `reports.generate_for_website` | Async one-off | — |

Every purge task is **chunked** (500 or 1000 rows per pass) specifically to avoid
long-running transactions and lock contention. Every rollup and purge is idempotent.

---

## 26. Data retention

| Data | Retention | Mechanism |
|---|---|---|
| `ScriptSnapshot` (raw payloads) | 90 days | `scripts.purge_old_snapshots`, 500-row chunks |
| `ActivityLog` | 90 days | `audit.purge_old_logs`, 500-row chunks |
| `PhpError` | 90 days | `site_health.purge_old_php_errors`, 1000-row chunks |
| `Notification` (non-pending) | 90 days | `alerts.purge_old_notifications` |
| `MonitorCheck` (raw) | **35 days** | `monitors.purge_old_checks` — 5 days of margin over the 30-day uptime window |
| `MonitorUptimeRollup` | Indefinite | The durable long-term uptime record |
| `PerformanceReport` | 365 days | `performance.purge_old_reports` |
| `Script`, `ScriptChange`, `DetectedForm`, `JsError`, `FormSubmissionError` | Indefinite | Deactivated, not deleted |
| `Credential`, `CredentialAccessLog`, `CredentialShare` | Indefinite | Access log is append-only |
| `Report` files | Indefinite | Deleted with the row |
| `Client` | Indefinite | Soft-delete via `status=offboarded` |
| Redis: pre-auth session | 300 s | `preauth:<key>` |
| Redis: pending TOTP secret | 600 s | `totp_pending:<user_pk>` |
| Redis: device trust | 10 hours | `device_trust:<token>` |
| Redis: extension handoff code | 60 s, single-use | `ext_handoff:<code>` |

---

## 27. Non-functional requirements

### 27.1 Security

| Control | Implementation |
|---|---|
| Encryption at rest | Fernet AES for credential username/password/notes, TOTP secrets, ClickUp tokens. Keys in env vars only, rotatable via `MultiFernet` |
| Password storage | Django's default PBKDF2 hasher; four validators (similarity, min length, common password, numeric-only) |
| 2FA | Mandatory in production. TOTP `valid_window=1`, 8 single-use backup codes stored as SHA-256 hashes, 10-hour device trust |
| Transport | nginx TLS; HSTS 1 year with `includeSubDomains` + `preload`; secure session/CSRF cookies |
| Token handling | JWTs only in HttpOnly cookies; browser JS never holds one |
| Tenant isolation | Queryset-level `for_team`, `TeamScopedMixin`, `IsTeamMember`, plus assignment restriction |
| SSRF | `assert_public_url()` on every user-supplied fetch, resolving and checking **all** addresses |
| CSP | Enforced in production, `frame-ancestors 'none'`, `base-uri 'none'` |
| Clickjacking | `X_FRAME_OPTIONS = "DENY"` |
| MIME sniffing | `SECURE_CONTENT_TYPE_NOSNIFF` |
| CORS | Explicit allowlist; production asserts no localhost origin |
| Rate limiting | Seven scopes; ingest bucketed per `site_id`; dedicated tight `auth` scope for brute force |
| Ingest trust | `site_id` + origin/referer host binding on all five public ingest endpoints |
| Payload bounds | 1 MB ingest, 5 MB credential CSV, 2 MB SEO fetch, 4096-byte monitor body read |
| Audit trail | 60 action types; append-only; failures never crash the caller |
| PII minimisation | Form-error and JS-error sanitisation (emails, secrets, long digit runs, sensitive query params); coarse browser family instead of full UA |
| Information non-disclosure | Extension lookup omits full script URLs; noise/validation errors return 202 without storing so probing reveals nothing; password reset does not confirm address existence |
| Secret display | Backup codes and WP SSO secrets shown exactly once |
| Least privilege | `CredentialAccessLog` documented as INSERT-only for the app's DB user |

### 27.2 Performance

Measures actually taken, each with a recorded reason:

- **Ingest returns 202 in < 50 ms** — all work deferred to Celery.
- **`WebsiteViewSet.list()` does not recalculate health.** It used to, costing ~8
  queries and a write per site: **1.03 s for 13 sites**, six to seventeen times every
  other dashboard call, on the critical path of every page load and filter change,
  growing linearly.
- **Team-wide `/changes/`, `/forms/`, `/form-errors/`** replaced one request per
  website (60+ for a real agency) with a single query.
- **Dashboard** issues 12 parallel requests, fetches the widest trend window once and
  slices client-side, and reads `member_count` off `/auth/teams/` to kill two
  sequential round trips.
- **Bulk name resolution** in the activity log: two queries per page regardless of
  size, instead of one per row.
- **`select_related` / `prefetch_related`** throughout (`domain_info`, `client`,
  `notification_channel`, `monitors`, `script`, `acknowledged_by`,
  `monitors__monitor`, `incidents`, `maintenance_windows`).
- **`F()` expressions** for `JsError.hits` and `DetectedForm.submission_count` so
  concurrent increments don't lose counts.
- **Bulk `.update()`** for acknowledgement, review and deactivation paths.
- **Health recalculated once per website** in bulk operations, which also fixes a
  real race.
- **Monitor health recalculation only on a status flip**, not every 30 s.
- **Snapshot dedupe on normalised URLs** — the whole point of §9.2 is that raw-URL
  diffing minted rows and events on every plugin update.
- **Snippet `MutationObserver` disconnects after 30 s**; JS errors capped at 10 per
  page load; stacks truncated to 5 frames.
- **Snippet cached 300 s** at `/api/s.js`.
- **Sitemap index traversal bounded** to one level and 10 children; SEO indexability
  bounded to 15 pages per run via a rotating cursor.
- **Purges chunked** at 500–1000 rows.

Indexes are declared on every hot path: `(team, status)`, `(team, is_vip)`,
`(domain)`, `(website, is_active, category)`, `(website, provider)`,
`(website, page_url, -captured_at)`, `(website, -created_at)`,
`(website, severity, acknowledged_at)`, `(monitor, checked_at)`,
`(website, strategy, -checked_at)`, `(team, read, -created_at)`,
`(team, delivery_status)`, `audit_team_created_idx`, `audit_actor_created_idx`.

### 27.3 Reliability

- **Every external call is wrapped.** WHOIS, hosting, SSL, SMTP, DNS, PSI, CrUX,
  WPScan, wordpress.org, ClickUp and Slack each degrade one field or one section
  rather than failing the request. `DomainIntelligenceService.check()` explicitly
  "never raises".
- **Failures are recorded, not swallowed.** `PerformanceReport.error`,
  `SiteScanState.error`, `SeoReport.error`, `SecurityHeaderReport.error`,
  `Report.error`, `Notification.error_message` all persist the reason.
- **Idempotency** on rollups, purges, `update_or_create` upserts, status-page
  provisioning, and `deliver_notification` (early return when already sent).
- **Retry-before-alert** on monitors (`retry_count`) and no duplicate alerts while
  down (`is_alerting`).
- **Undelivered domain alerts stay unsent** so the next check retries them.
- **Audit writes never crash the caller.**
- **Dead-man's-switch heartbeat** detects a stalled beat or worker.
- **`transaction.atomic`** wraps the whole ingest body and all team/credential
  service mutations; `select_for_update` on invitation acceptance.
- **Self-healing** health/status on `retrieve()` plus the nightly sweep.

### 27.4 Usability and accessibility

Server-rendered pages with `loading.tsx` skeletons; light/dark via `next-themes`;
toast feedback; Radix primitives supplying keyboard navigation and ARIA semantics; the
extension dropdown implements arrow-key navigation and focus management explicitly.
Error messages are written to be actionable — the PSI 429 names the env var and signup
URL, the CrUX 403 links the exact console page to enable the API, snippet verification
reports how many bytes it checked, and the extension save bar renders the API's own
"add the website first" text.

### 27.5 Maintainability

Pure, side-effect-free modules are the backbone of the testable surface:
`diff_engine`, `classifier`, `normalize`, `suspicion`, `js_errors`, `form_errors`,
`dedup`, `checker`, `header_checker`, `seo_checker` (parse functions),
`platform_detect`, `trends`, `features`, `ssrf`. Business logic sits in services
(`TeamService`, `CredentialService`, `AlertService`,
`AuditService`, `DomainIntelligenceService`, `PageSpeedService`, `CruxService`,
`ReportBuilder`). Comments in this codebase consistently record *why* a decision was
made and what broke before it — that is the primary maintenance aid and should be
preserved when editing.

---

## 28. Deployment, operations and testing

### 28.1 Deployment procedure

**Always `./deploy.sh`.** It refuses to run without `.env.production`, performs an
email pre-flight (rejecting a missing, `consolemail` or placeholder `EMAIL_URL`),
pulls `main`, rebuilds `api` / `celery` / `celery-beat` with the production compose
file, builds the frontend and `pm2 restart stacksmonitor-frontend`, then verifies
`https://stacksmonitor.com/api/s.js` actually serves the snippet.

Server path and command:

```bash
cd /home/stacksmonitor/app && ./deploy.sh
```

**Never run bare `docker compose up` on the server.** The default
`docker-compose.yml` is the dev file: it pins `config.settings.development`
(DEBUG=True, localhost-only `ALLOWED_HOSTS`), so public requests get
`DisallowedHost 400` and `/api/ingest/` and `/api/s.js` break. This exact drift once
ran dev settings in production for weeks.

After deploying, **hard-refresh the browser** — stale JS bundles produce "Failed to
find Server Action" errors until reload.

### 28.2 Required production environment

`.env.production` needs everything in `.env` plus:

```
ALLOWED_HOSTS=stacksmonitor.com
CORS_ALLOWED_ORIGINS=https://stacksmonitor.com
SNIPPET_CDN_URL=https://stacksmonitor.com/api
DB_PASSWORD=<postgres password>
EMAIL_URL=smtp+tls://LOGIN%40smtp-brevo.com:SMTP_KEY@smtp-relay.brevo.com:587
DEFAULT_FROM_EMAIL=<sender on a Brevo-authenticated domain>
```

`SNIPPET_CDN_URL` **must** end in `/api` — nginx proxies only `/api/...` to Django,
and `stacksmonitor.com` has no DNS record or vhost.

### 28.3 Migrations

The `api` container entrypoint runs `migrate` on every start, so a deploy applies
migrations automatically. Locally, `--create-db` must be passed to pytest after any
model or migration change, or the reused schema won't rebuild and tests error out.

Notable data migrations: `scripts/0009_merge_duplicate_scripts` (dedupe, §9.12),
`scripts/0010_script_unique_normalized`, `scripts/0011_merge_duplicate_forms`,
`scripts/0007_ack_changes_for_reviewed_scripts`,
`clients/0004_backfill_hosting_to_websites`, `monitors/0009_backfill_monitor_website`,
`domains/0002_mark_existing_alerts_sent`.

### 28.4 Management commands

- `rotate_vault_keys` — re-encrypt every vault blob under the new primary key.
- `purge_wp_core_scripts` — remove historically-collected WordPress core scripts.
- `seed_demo_data` — populate a demo team.

### 28.5 Testing

**82 test files** under `tests/`, mirroring the app layout: `accounts`, `alerts`,
`audit`, `chat`, `clients`, `common`, `credentials`, `domains`, `monitors`,
`performance`, `reports`, `scripts`, `site_health`, `status_pages`, `websites`.

```bash
pytest                                    # all
pytest tests/scripts/test_diff_engine.py  # one file
pytest --cov=apps                         # with coverage
pytest --create-db                        # REQUIRED after any model/migration change
```

Four conventions govern every test:

1. **Celery runs eagerly** (`CELERY_TASK_ALWAYS_EAGER`), so `.delay()` executes
   synchronously — posting to `/api/ingest/` runs the whole pipeline inline.
2. An **autouse fixture** `no_network_in_tests` in [tests/conftest.py](../tests/conftest.py)
   patches out the uptime, domain and performance network checks that fire during
   `Website` creation. New tests hitting other real network calls must mock them too.
3. `auth_client` / `developer_user` fixtures give authenticated clients; the JWT is at
   `response.data["access"]` because the token endpoint is **not** envelope-wrapped.
4. `response.data` in tests is the **raw** payload, bypassing
   `EnvelopeJSONRenderer` — assert `resp.data["..."]`, never `resp.data["data"]`.

`--reuse-db` makes re-runs fast, which is exactly why forgetting `--create-db` after a
model change produces confusing schema errors.

---

## Appendix A — Complete API catalogue

### A.1 Public / unauthenticated

| Method | Path | Auth model |
|---|---|---|
| GET | `/api/s.js` | None. `Cache-Control: max-age=300`, `ACAO: *` |
| POST | `/api/ingest/` | `site_id` + origin binding. 1 MB cap. → 202 |
| POST | `/api/ingest/js-errors/` | `site_id` + origin binding → 202 |
| POST | `/api/ingest/form-errors/` | `site_id` + origin binding → 202 |
| POST | `/api/ingest/form-submission/` | `site_id` + origin binding → 202 `{counted}` |
| POST | `/api/php-errors/` | `site_id` + origin binding → 202 `{accepted}` |
| GET | `/api/extension/lookup/?domain=` | None, throttled 300/hour. Max 10 sanitised entries |
| GET | `/api/extension/exchange/?code=` | The one-time code is the credential; single-use |
| GET | `/api/v1/public/status/<slug>/` | None |
| POST | `/api/v1/auth/register/` | None |
| POST | `/api/v1/auth/login/` | Credentials, `auth` throttle |
| POST | `/api/v1/auth/first-password/` | Pre-auth `session_key` |
| POST | `/api/v1/auth/2fa/verify/` | Pre-auth `session_key` + code, 10/min |
| POST | `/api/v1/auth/token/`, `/token/refresh/` | SimpleJWT (**not** envelope-wrapped) |
| POST | `/api/v1/auth/password-reset/` | None |
| POST | `/api/v1/auth/password-reset/confirm/` | Reset token |
| GET | `/api/v1/auth/invitations/<token>/` | Invitation token |
| GET | `/admin/` | Django session |
| WS | `/ws/alerts/` | JWT via subprotocol, header or query |

### A.2 Authenticated (JWT + team scope)

**Auth & teams** — `GET/PATCH /api/v1/auth/me/` · 2FA `setup`, `confirm`, `disable`,
`regenerate-backup`, `status` · `GET/POST teams/` · `GET/PATCH teams/<pk>/` ·
`GET teams/<t>/members/` · `PATCH/DELETE teams/<t>/members/<pk>/` ·
`POST teams/<pk>/switch/` · `POST teams/<t>/invite/` · `POST teams/<t>/users/` ·
`GET teams/<t>/invitations/` · `DELETE teams/<t>/invitations/<pk>/` ·
`GET/PATCH teams/<pk>/settings/` · `POST teams/<pk>/settings/clickup-test/` ·
`POST invitations/<token>/accept/` · `GET password-reset/` ·
`POST password-reset/<pk>/approve/` · `POST password-reset/<pk>/reject/`

**Websites** — `GET/POST /api/v1/websites/` · `GET/PATCH/DELETE <pk>/` ·
`GET <pk>/health/` · `GET <pk>/snippet/` · `POST <pk>/regenerate-snippet/` ·
`GET/POST <pk>/scan/` · `POST <pk>/verify-snippet/` · `GET/PUT <pk>/assignments/` ·
`POST <pk>/wp-sso-secret/` · `POST <pk>/wp-login/` · `GET expiring-domains/` ·
`GET expiring-ssl/` · `GET expiring-hosting/`

**Scripts, forms, errors** — `GET websites/<w>/scripts/` ·
`PATCH websites/<w>/scripts/<pk>/review/` · `POST websites/<w>/scripts/bulk-review/` ·
`GET websites/<w>/scripts/<pk>/timeline/` · `GET websites/<w>/changes/` ·
`GET changes/` · `POST changes/<pk>/acknowledge/` ·
`POST changes/bulk-acknowledge/` · `GET websites/<w>/forms/` · `GET forms/` ·
`GET websites/<w>/form-errors/` · `GET form-errors/` · `GET websites/<w>/js-errors/`

**Credentials** — `GET/POST credentials/` · `POST credentials/import/` ·
`GET/POST websites/<w>/credentials/` · `GET/PATCH/DELETE credentials/<pk>/` ·
`POST credentials/<pk>/reveal/` · `GET websites/<w>/credential-audit/` ·
`POST websites/<w>/credentials/share/` · `GET/POST credentials/<pk>/shares/` ·
`DELETE credentials/<pk>/shares/<user_id>/` ·
`GET /api/extension/credentials/` · `POST /api/extension/credentials/save/` ·
`POST /api/extension/web-handoff/` · `POST /api/extension/token/`, `/token/refresh/`

**Domains** — `GET websites/<w>/domain/` · `POST websites/<w>/domain/refresh/`

**Alerts** — `GET/POST alert-rules/` · `GET/PATCH/DELETE alert-rules/<pk>/` ·
`GET notifications/` · `POST notifications/mark-read/` ·
`GET/POST websites/<w>/alert-suppressions/` · `DELETE alert-suppressions/<pk>/`

**Monitors** — `GET/POST monitors/` · `GET monitors/uptime-trend/` ·
`GET/PATCH/DELETE monitors/<pk>/` · `GET monitors/<pk>/checks/` ·
`POST monitors/<pk>/pause/` · `/resume/` · `/check-now/` ·
`GET/POST notification-channels/` · `GET/PATCH/DELETE notification-channels/<pk>/` ·
`POST notification-channels/<pk>/test/` ·
`GET/POST monitors/<pk>/notification-rules/` ·
`GET/PATCH/DELETE monitors/<pk>/notification-rules/<pk>/`

**Performance** — `GET websites/<w>/performance/` · `POST …/performance/run/` ·
`GET …/performance/trends/` · `GET websites/<w>/crux/` · `POST …/crux/run/`

**Site health** — `GET websites/<w>/php-errors/` · `GET websites/<w>/events/` ·
`POST websites/<w>/events/create/` · `GET websites/<w>/vulnerabilities/` ·
`GET/POST websites/<w>/scan/` · `GET websites/<w>/security-headers/` ·
`GET websites/<w>/seo/`

**Status pages** — `GET/POST status-pages/` · `GET/PATCH/DELETE status-pages/<pk>/` ·
`GET/POST status-pages/<pk>/monitors/` ·
`GET/PATCH/DELETE status-pages/<pk>/monitors/<pk>/` ·
`GET/POST status-pages/<pk>/incidents/` ·
`GET/PATCH/DELETE status-pages/<pk>/incidents/<pk>/` ·
`GET/POST status-pages/<pk>/maintenance/` ·
`GET/PATCH/DELETE status-pages/<pk>/maintenance/<pk>/`

**Clients** — `GET/POST clients/` · `GET clients/search/` · `POST clients/import/` ·
`GET clients/export/` · `GET/PATCH clients/<pk>/` · `POST clients/<pk>/activate/` ·
`POST clients/<pk>/deactivate/`

**Reports** — `GET reports/` · `POST reports/generate/` ·
`GET reports/<pk>/download/` · `DELETE reports/<pk>/`

**Audit** — `GET logs/` · `GET logs/export/`   **Chat** — `POST chat/`

---

## Appendix B — Complete model inventory

| App | Model | Base | Key constraint |
|---|---|---|---|
| accounts | `User` | `AbstractUser` | unique `email`, unique `username` |
| accounts | `Team` | `BaseModel` | unique `slug` |
| accounts | `TeamMembership` | `BaseModel` | unique `(user, team)` |
| accounts | `TeamInvitation` | `BaseModel` | unique `(team, email)`, unique `token` |
| accounts | `PasswordResetRequest` | `BaseModel` | unique `reset_token` |
| websites | `Website` | `BaseModel` | unique `site_id` |
| websites | `WebsiteAssignment` | `BaseModel` | unique `(website, user)` |
| clients | `Client` | `BaseModel` | — |
| scripts | `Script` | `BaseModel` | unique `(website, normalized_url)` |
| scripts | `ScriptSnapshot` | `BaseModel` | — |
| scripts | `ScriptChange` | `BaseModel` | — |
| scripts | `DetectedForm` | `BaseModel` | unique `(website, page_url, fingerprint)` |
| scripts | `JsError` | `BaseModel` | unique `(website, fingerprint)` |
| scripts | `FormSubmissionError` | `BaseModel` | — |
| credentials | `Credential` | `BaseModel` | — |
| credentials | `CredentialShare` | `BaseModel` | unique `(credential, user)` |
| credentials | `CredentialAccessLog` | `BaseModel` | append-only |
| domains | `DomainInfo` | `BaseModel` | OneToOne `website` |
| domains | `DomainAlert` | `BaseModel` | unique `(domain_info, alert_type, days_until_expiry)` |
| alerts | `AlertRule` | `BaseModel` | — |
| alerts | `AlertSuppression` | `BaseModel` | unique `(website, match_type, match_value)` |
| alerts | `Notification` | `BaseModel` | — |
| monitors | `Monitor` | own UUID pk | — |
| monitors | `MonitorCheck` | own UUID pk | — |
| monitors | `MonitorUptimeRollup` | own UUID pk | unique `(monitor, date)` |
| monitors | `NotificationChannel` | own UUID pk | — |
| monitors | `MonitorNotificationRule` | own UUID pk | unique `(monitor, channel)` |
| performance | `PerformanceReport` | own UUID pk | — |
| performance | `CruxReport` | own UUID pk | — |
| site_health | `PhpError` | `BaseModel` | — |
| site_health | `SiteEvent` | `BaseModel` | — |
| site_health | `VulnerabilityReport` | `BaseModel` | unique `(website, component_name, title)` |
| site_health | `SiteScanState` | `BaseModel` | OneToOne `website` |
| site_health | `SeoReport` | `BaseModel` | OneToOne `website` |
| site_health | `SecurityHeaderReport` | `BaseModel` | OneToOne `website` |
| status_pages | `StatusPage` | own UUID pk | unique `slug` |
| status_pages | `StatusPageMonitor` | own UUID pk | unique `(status_page, monitor)` |
| status_pages | `StatusPageIncident` | own UUID pk | — |
| status_pages | `MaintenanceWindow` | own UUID pk | — |
| reports | `Report` | `BaseModel` | — |
| audit | `ActivityLog` | `BaseModel` | append-only |

**41 concrete models** (plus the abstract `apps.common.BaseModel`, which is never
queried directly).

---

## Appendix C — Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | **Yes** | — | Django signing key, 50 chars |
| `DEBUG` | No | `False` | Debug mode |
| `ALLOWED_HOSTS` | Prod | `[]` | Comma list; production appends `127.0.0.1`, `localhost` |
| `DATABASE_URL` | **Yes** | — | Postgres DSN |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Cache, broker, Channels |
| `VAULT_ENCRYPTION_KEY` | One of | `""` | Legacy single Fernet key |
| `VAULT_ENCRYPTION_KEYS` | One of | `[]` | Ordered rotation list; first encrypts |
| `EMAIL_URL` | **Prod** | `consolemail://` | Production **refuses to boot** on blank/console |
| `DEFAULT_FROM_EMAIL` | No | `Stacks Monitor <noreply@stacksmonitor.com>` | Sender |
| `FRONTEND_URL` | No | `http://localhost:3000` | Links in emails |
| `SNIPPET_CDN_URL` | Prod | `https://stacksmonitor.com` | Snippet base; must end `/api` in production |
| `CORS_ALLOWED_ORIGINS` | Prod | — | Asserted non-localhost in production |
| `JWT_ACCESS_TOKEN_LIFETIME_MINUTES` | No | `15` | Access token TTL |
| `JWT_REFRESH_TOKEN_LIFETIME_DAYS` | No | `7` | Refresh token TTL |
| `THROTTLE_ANON` / `_USER` / `_AUTH` / `_INGEST` / `_EXTENSION` | No | `1000/hour` / `10000/day` / `120/minute` / `10000/day` / `300/hour` | Rate limits (see §16.2 for the ingest caveat) |
| `PAGESPEED_API_KEY` | No | `""` | PSI quota; also used for CrUX |
| `WPSCAN_API_KEY` | No | *(unset)* | Real CVE lookups; absent → heuristic scan |
| `CLICKUP_API_TOKEN` | No | `""` | Global ClickUp fallback |
| `SENTRY_DSN` | No | `""` | Enables Sentry when set |
| `SENTRY_ENVIRONMENT` | No | `production` | Sentry tag |
| `SENTRY_TRACES_SAMPLE_RATE` | No | `0.0` | Tracing sample (production override 0.1) |
| `LOG_LEVEL` | No | `INFO` | Root log level |
| `HEARTBEAT_PING_URL` | No | `""` | Dead-man's-switch target |
| `DB_PASSWORD` | Prod | — | Postgres password for compose |
| `NEXT_PUBLIC_API_URL` | Frontend | `http://localhost:8000` | Django base URL |

---

*End of specification. Part 1: [`srs.md`](srs.md).*
