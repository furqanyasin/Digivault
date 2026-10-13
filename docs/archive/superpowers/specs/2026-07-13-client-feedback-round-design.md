# Client Feedback Round — Design & Decomposition (2026-07-13)

Source: client discussion covering ~30 change requests across forms, scripts,
monitoring, notifications, change log, security, hosting, access, and the
client section. This spec maps each request to the existing codebase, states
what is already built, and decomposes the rest into seven independently
shippable phases. Each phase gets its own implementation plan.

## Current-state findings (what already exists)

| Request | Existing code | Gap |
|---|---|---|
| Active/Inactive per script | `Script.is_active` (model), shown only in Tracking tab | Not shown in Scripts tab |
| Approve/Decline scripts | `Script.review_status` (pending/approved/blocked/ignored), `script-review-button.tsx`, `SCRIPT_REVIEWED` audit action | Verify decline UI; score impact unverified |
| Change log w/ user | `ScriptChange` + Change Log tab; `acknowledged_by`; `ActivityLog.actor` | No unified per-site summary combining both |
| User activity log | `apps/audit.ActivityLog` + `/logs` page | No per-website filter |
| Per-website notifications | `AlertRule.website` (nullable = global) | No per-site channel UX; settings duplicated |
| Elementor form detection | `snippet.js`: `elementor-form` class, `elementor/popup/show` listener, MutationObserver | Needs verification against a real careers page |
| Domain renewal date | `apps/domains` WHOIS checks; `Client.hosting_renewal_date`, `contract_renewal_date` | Not auto-populated into Client; no setup-flow capture |

## Phase 1 — Data-correctness bugs (highest priority)

These are trust-destroying bugs; everything else is cosmetic until counts are
right. Each is an investigate-first task (systematic-debugging): reproduce
with a failing test before changing code.

### 1.1 Forms: one page counted twice

`DetectedForm` is unique per `(website, page_url, fingerprint)`. Two likely
causes, both to be confirmed by reproducing with real payloads:

- **page_url variance** — querystrings, hash fragments, trailing slash, or
  `www.` differences make the same page produce distinct rows. Fix: normalize
  `page_url` at ingest (strip query + hash, canonical trailing slash) and add
  a data migration that merges existing duplicates (keep earliest
  `first_seen_at`, latest `last_seen_at`).
- **fingerprint instability** — plugins that render per-pageload field names
  (nonces, honeypots, `_wpcf7_unit_tag`) change the fingerprint every load.
  Fix: exclude volatile field-name patterns (`_wp*nonce*`, `hp-*`, hash-like
  names) from the fingerprint basis.

### 1.2 Forms: count only WordPress-managed forms

Add `DetectedForm.is_managed` (derived, not user-set): `detection_type` in
(native, dom) with a recognized WP form plugin source ⇒ managed. `EMBEDDED`
(iframe, e.g. ISA) ⇒ unmanaged. Forms tab counts and headline number use
managed forms only; embedded third-party forms collapse into a separate
"Third-party embeds" section labeled as unverifiable (their fields are
cross-origin and unreadable — CLAUDE.md already documents this).

### 1.3 Forms: verify Elementor pickup

Snippet already handles Elementor. Task: capture a real payload from the
client's jobs/careers page, add it as a test fixture, and fix whatever the
fixture reveals (likely popup-only or AJAX-rendered timing). No speculative
code before the fixture exists.

### 1.4 Scripts: over-counting (~25 rows for 3–4 real scripts)

`Script` is unique per `(website, src_url)` and WordPress emits cache-busted
URLs (`?ver=6.4.2`, `?nonce=…`), so every plugin update or nonce rotation
mints a "new" script row and an `added` ScriptChange. Design:

- Add `Script.normalized_url` (indexed): `src_url` minus volatile params
  (`ver`, `nonce`, `cb`, `_`, `t`, timestamp-like values). Meaningful params
  (`id=GTM-XXX`, `id=AW-XXX`, `render=`) are kept — the param whitelist per
  provider lives next to `ScriptClassifier`.
- Uniqueness and DiffEngine keying move to `normalized_url`. A `ver=` bump
  becomes a low-severity `url_changed` event, not `added` + `removed`.
- Data migration merges existing duplicate rows (union `seen_on_pages`,
  earliest first_seen, latest last_seen, keep any non-pending review_status).

This also fixes "per page and per date" re-logging: the ScriptChange log only
gets a row when the normalized set actually changes.

### 1.5 Google Ads click-through URL looks short/wrong

Investigate what is actually captured for Google Ads scripts (likely showing
`src_domain` or a truncated `smartUrl()` rendering rather than the full
`src_url` with the `AW-` conversion ID). Reproduce first; fix is either in
`ScriptClassifier` pattern extraction or the frontend URL display.

## Phase 2 — Scripts UX consolidation

- **Active/Inactive badge** in `scripts-tab.tsx` on every row (reuse the
  Tracking tab's indicator styling).
- **Remove the Tracking tab** (`tracking-tab.tsx`, its TabsTrigger/Content in
  the website detail page) once the badge ships.
- **Review filter** (All / Pending / Approved / Rejected) on the Scripts tab —
  client-side filter over the already-fetched list.
- **Approve/Decline on each row** — surface the existing review actions on the
  list, not only in the detail dialog.
- **Score impact**: site health score gains a "script review" component —
  ratio of approved to total active scripts. (Verify how `apps/site_health`
  computes the score and add the factor there.)

## Phase 3 — Client model overhaul

Model + serializer + form changes in `apps/clients` and `clients-client.tsx`:

- **Remove** `migration_status`, `csm_migration_confirmation`,
  `clickup_task_id`, `clickup_synced_at`, `comments`, `contract_renewal_date`
  and their UI. Migration drops columns after a release with them hidden.
- **Status** becomes active / paused / offboarded (map `inactive` →
  `offboarded` in the migration).
- **Tier** field (gold / silver / bronze / none) — replaces `support_tier`
  labels or is added alongside; recommendation: rename/remap `support_tier`
  choices to tiers so no second field exists.
- **Client name required** — already NOT NULL; enforce non-blank in serializer
  + required marker in the form.
- **Hosting**: keep `hosting_platform` choices; add `hosting_platform_other`
  text field shown conditionally when "Other" selected; tooltip copy for each
  hosting type (delegate etc.) in the form.
- **Website access level** field (choice: full admin / delegate / none…) with
  tooltip.
- **Department separation** (SEO / Ads / Dev): `Client.departments` M2M or
  choices multi-select controlling which team members see the client — feeds
  Phase 7 assignment work; in Phase 3 it is just a stored field.
- **Domain renewal date** field, auto-populated from the domains app WHOIS
  expiry when the client's domain matches a monitored website; manual
  override allowed.
- **Hosting renewal in setup flow**: new-client / new-website forms capture
  hosting platform + renewal date once; hosting provider auto-detected where
  possible (nameserver/header heuristics in the existing domain check task);
  renewal date stays manual when not detectable (it is almost never public —
  only domain expiry is, via WHOIS).
- **Notification toggles**: per-user Desktop + Email toggles (browser push =
  desktop; stored on user/team notification preferences, honored by
  `apps/alerts` delivery dispatch).

## Phase 4 — Notifications consolidation

- **One place per site**: the website detail page becomes the single per-site
  notification settings surface. The global settings screen keeps only
  team-level defaults; remove the duplicated per-site toggles there.
- **Per-website channel**: on website creation, auto-create a per-website
  `AlertRule` set so each site's alerts are independently toggleable (the
  model already supports `website`-scoped rules — this is default-creation +
  UI, not schema work).
- **Uptime as separate channel**: monitor (up/down) alerts get their own rule
  category, separately toggleable from script/content alerts, so downtime
  notifications route independently.

## Phase 5 — Monitoring merged into website pages

- Add an **Uptime section** on the website detail page: current status,
  uptime %, response chart, incidents (reuse `monitor-response-chart.tsx`,
  `uptime-heatmap.tsx`, `monitor-actions.tsx`).
- Link monitors to websites (verify/add `Monitor.website` FK; auto-associate
  by domain for existing monitors in a migration).
- **Remove the Monitors sidebar entry**; monitor create/edit moves into the
  website page. Keep backend routes intact.

## Phase 6 — Change log & security polish

- **Unified per-site change log**: merge `ScriptChange` events with relevant
  `ActivityLog` entries (script reviewed, website updated) into one
  high-level feed with the acting user shown; collapse noisy runs (N changes
  on one day → one summary row, expandable).
- **Activity Log**: add website filter to `/logs`; keep it user-centric
  (already actor-based) — this is the "user activity" view, distinct from the
  per-site technical change log.
- **Security plugin detection**: extend classification to recognize security
  plugins from script paths (`/wp-content/plugins/wordfence/…`, Sucuri, iThemes
  etc.) and surface "Security plugin: Wordfence" on the Security tab. Purely
  passive — no new collection needed; plugin paths already arrive via the
  snippet (`wp_plugin` enrichment exists on `Script`).

## Phase 7 — Access: one-click WP login & per-website assignment

Largest and riskiest phase; ships last, likely as two sub-projects.

### 7.1 Per-website user assignment
- `WebsiteAssignment` (website, user, optional department) model.
- Non-manager users with assignments see only assigned websites/clients:
  enforced in `TeamScopedMixin`/querysets, not just hidden in the UI.
- Team page UI to assign users to websites; department field from Phase 3
  can drive bulk assignment.

### 7.2 One-click login into the client's WP admin
Requires a WP-side component — recommendation: a small Digivault companion
WordPress plugin (wp-plugin-dev skill when built) that:
- registers a REST endpoint accepting a short-lived signed token from
  Digivault, verifies HMAC with a per-site shared secret, and creates a WP
  session for a mapped role (Owner → administrator, Developer → editor/admin
  per config);
- Digivault side: "Login" button on the website page generates the one-time
  URL; every use writes an `ActivityLog` entry; button visibility respects
  role + Phase 7.1 assignment.
- Fallback where the plugin can't be installed: existing vault autofill via
  the Chrome extension remains the path.

## Explicit decisions (made without further input, flag if wrong)

1. Hosting renewal dates are treated as **not auto-fetchable** (not public);
   only domain expiry auto-populates from WHOIS. Hosting *provider* is
   auto-detected where possible.
2. `support_tier` is remapped to the Tier field (gold/silver/bronze) rather
   than adding a parallel field.
3. Removed client fields are dropped via migration after one release of being
   hidden in the UI (data preserved in DB until the drop migration runs).
4. The Monitors backend stays; only the navigation/UX moves into website
   pages.
5. Phase 1 bugs are fixed by URL/fingerprint normalization at ingest with
   merge migrations — not by display-side dedup, which would leave the data
   wrong.

## Testing approach

Every Phase 1 fix starts from a failing test using a captured real payload
(fixtures under `tests/scripts/fixtures/`). Model changes need `--create-db`.
Diff-engine changes stay pure-function tested. Frontend changes verified via
`npm run build` + manual pass. Phases are separate branches/PRs in the order
listed; Phase 1 and Phase 3 are independent and can run in parallel.
