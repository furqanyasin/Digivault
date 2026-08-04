# Integrations: ClickUp sync & removing the Excel dependency

**Date:** 2026-07-31
**Status:** Research + plan. No code written.
**Goal:** Sync CSM client data from ClickUp automatically, so the CSV round-trip
stops being the way data gets into Digivault.

---

## 1. What already exists

The picture is better than it looks: ClickUp is already wired **outbound**, and
the hardest part of an inbound sync — translating ClickUp's field vocabulary into
Digivault's — is already written inside the CSV importer.

### Live today

| Piece | Where | Notes |
|---|---|---|
| Encrypted per-team API token | `Team._clickup_api_token` (`accounts/models.py:87`) | `BinaryField` + Fernet via `clickup_api_token` property. Never in plaintext at rest. |
| Token settings endpoint | `TeamSettingsView` (`accounts/views.py:851`) | Manager+ only; audited as `settings.integration_updated`. |
| Connectivity check | `ClickUpTestView` (`accounts/views.py:862`) | `GET /api/v2/user`, returns `{connected, clickup_user}`. |
| Outbound messages | `post_clickup()` (`monitors/notifications.py:71`) | Chat channel via v3, or task comment via v2. Powers the `clickup` notification channel. |
| Global token fallback | `CLICKUP_API_TOKEN` (`config/settings/base.py:314`) | Env-level default. |

### Does NOT exist

- **No inbound sync of any kind.** No ClickUp → Client import, no Celery task.
- **No mapping key.** `Client` has no `clickup_task_id`. Nothing ties a Digivault
  client to a ClickUp task.
- **`CLIENT_SYNCED` is dead code.** `ActivityLog.Action.CLIENT_SYNCED`
  (`"Client synced from ClickUp"`, `audit/models.py:59`) is declared and **never
  written anywhere**. It was added in anticipation of this work.

### The current Excel workflow

```
ClickUp  →  export CSV  →  human opens/edits in Excel  →  POST /api/v1/clients/import/  →  Client rows
```

`ClientImportView` (`clients/views.py:~420-513`) already:

- Accepts **legacy ClickUp export headers** alongside current ones —
  `"Task Name"` for `"Client Name"`, `"Where we have the domain access (drop down)"`
  for `"Domain Access"`, `"Website built by Digi  (drop down)"`, etc. Those `(drop down)`
  suffixes *are* ClickUp custom-field names.
- Normalises ClickUp's dropdown wording through `_parse_hosting`, `_parse_status`,
  `_parse_tier`, `_parse_date`, `_parse_bool`.
- Keeps unrecognised hosting wording in `hosting_platform_other` rather than
  dropping it.
- Calls `_auto_create_website()` then `_sync_hosting_to_websites()` per row, so an
  import also provisions the website.

**This is the single most important finding: the field-mapping and value-coercion
logic for ClickUp data is already written and in production use.** An API sync
should reuse those parsers, not reinvent them.

### The 16 canonical fields (`EXPORT_HEADERS`, `clients/views.py:174`)

Client Name · Websites URL · Status · Tier · Hosting Platform · Hosting Platform
(Other) · Website Access Level · Domain Access · Hosting Renewal Date · Domain
Renewal Date · Website Built by Digi · Website Maintained by Digi · Departments ·
Desktop Notifications · Email Notifications · Notes

---

## 2. Problems with the current approach

### 2.1 The upsert key is the client **name**

```python
Client.objects.update_or_create(team=team, name=name, defaults=defaults)
```

Consequences:

- Rename a client in ClickUp → **a duplicate is created** in Digivault, and the
  old row lingers with stale renewal dates still feeding the Renewal Center.
- Two clients with the same name can never coexist.
- Fixing a typo in a name silently forks the record.

A stable external id is a prerequisite for any real sync, not an optimisation.

### 2.2 The CSV is a lossy, manual, unaudited hop

- **Manual cadence.** Data is only as fresh as the last person who remembered to
  export. Renewal dates are exactly the data where staleness causes a missed
  renewal.
- **Excel mangles dates.** A `YYYY-MM-DD` column becomes locale-dependent on open
  and save. `_parse_date` compensates, which is itself evidence of the problem.
- **No provenance.** After import, nothing records which values came from ClickUp
  versus which a person typed in Digivault. So a re-import overwrites local edits
  with no warning, and there is no way to tell that it happened.
- **Blind to deletions.** A task deleted or archived in ClickUp leaves its client
  active in Digivault forever.
- **All-or-nothing.** The endpoint reports `created/updated/skipped` counts, but a
  partially bad sheet gives no per-row remediation path.

### 2.3 Direction is undefined

Nothing states whether ClickUp or Digivault owns a given field. Today it is
implicitly "whoever imported last". That is the actual root problem — and it is a
policy decision, not a technical one.

---

## 3. Proposed design

### 3.1 Ownership model — decide this first

Everything else follows from it. Recommendation:

| Field group | Owner | Why |
|---|---|---|
| Name, Status, Tier, Departments, Notes | **ClickUp** | CSM-managed commercial facts; ClickUp is where account managers already work. |
| Hosting Platform, Domain Access, Website Access Level, renewal dates | **ClickUp initially, Digivault after first local edit** | Ops correct these while working; a sync must not clobber that. |
| Everything observed — scripts, uptime, SSL, health, performance | **Digivault only** | ClickUp never has this data. Never written by sync. |

The middle row is the one that needs a mechanism: **per-field provenance**. Store
which fields were last set by sync; if a human has since edited a field, sync
records a *conflict* rather than overwriting.

Simpler alternative if that's too much for v1: **ClickUp wins on every mapped
field**, and the UI marks those fields read-only with a "managed in ClickUp" hint.
Honest and predictable, at the cost of forcing corrections upstream. Worth
considering as the actual v1.

### 3.2 Schema additions

On `Client`:

- `clickup_task_id` — indexed, unique per team, blank for locally-created clients.
  **The mapping key.** Its absence is why sync can't exist today.
- `clickup_synced_at` — last successful sync.
- `clickup_synced_fields` (JSON) — provenance for the conflict rule above.
- `sync_status` — `ok` / `conflict` / `orphaned` (task gone from ClickUp).

On `Team` (integration config):

- `clickup_list_id` — which ClickUp List holds client tasks. Required; a token
  alone doesn't say *what* to sync.
- `clickup_field_map` (JSON) — ClickUp custom-field id → Digivault field. Custom
  fields are addressed by **id**, not name, and ids differ per workspace, so this
  cannot be hardcoded.
- `clickup_sync_enabled`, `clickup_sync_interval_minutes`.

A new `IntegrationSyncRun` model for observability: started/finished, counts
(created/updated/conflicted/skipped), and per-row errors. Without this, a
scheduled sync is a silent background process nobody trusts.

### 3.3 Sync engine shape

Follow the established pattern in this codebase: **pure functions + a thin Celery
task**, mirroring `DiffEngine` and `monitors/checker.py`.

- `apps/integrations/clickup/client.py` — API wrapper. Paginated list fetch,
  rate-limit handling, timeouts. ClickUp allows ~100 req/min per token, so
  fetching one List page-by-page matters.
- `apps/integrations/clickup/mapper.py` — **pure**: ClickUp task dict + field map
  → Digivault field dict. No DB access, so it's cheaply unit-testable.
  **Reuses the existing `_parse_*` helpers**, which should move out of
  `clients/views.py` into a shared module first (they're import-time helpers doing
  domain work in a view file).
- `apps/integrations/clickup/sync.py` — reconciliation: match by
  `clickup_task_id`, fall back to name for first-run adoption, apply the ownership
  rule, record conflicts.
- `integrations.sync_clickup_clients` Celery task, on Beat. Per-team, guarded by a
  Redis lock so a slow run can't overlap itself.

### 3.4 First-run adoption

Existing clients have no `clickup_task_id`. The first sync must **adopt, not
duplicate**: match on normalised name, then on `website_url` domain (the same
two-key approach `_auto_create_website` already uses), and record the id. Anything
unmatched is reported for review rather than auto-created — a silent bulk create
on first run would be the worst possible first impression.

### 3.5 Handling deletions

A task that vanishes from the List marks its client `sync_status="orphaned"` and
raises it in the UI. **Never auto-delete** — `Client` is deliberately soft-deleted
via `status=offboarded` and never hard-deleted (per its own docstring), and a
ClickUp permission change could otherwise wipe real records.

---

## 4. Phasing

Each phase is independently shippable and useful on its own.

### Phase 1 — Make sync possible (no behaviour change)
- Add `clickup_task_id` + sync metadata to `Client`; migration.
- Extract `_parse_*` helpers out of `clients/views.py` into a shared module.
- Backfill: record `clickup_task_id` on CSV import when the sheet carries a task id
  column, so future syncs have a key.
- **Fix the name-based upsert** to prefer `clickup_task_id` when present.
- *Value on its own:* stops re-imports duplicating renamed clients.

### Phase 2 — Read-only pull, manual trigger
- ClickUp API client + mapper + a "Sync now" button on the integration settings page.
- Show a **dry-run diff first**: what would change, per client, before writing.
- Write `CLIENT_SYNCED` audit entries — finally giving that enum a use.
- *Value:* replaces the export→Excel→import loop with one click, and the dry run
  builds trust before automation.

### Phase 3 — Scheduled sync + conflict surface
- Celery Beat entry, per-team interval, Redis lock.
- `IntegrationSyncRun` history view; conflicts listed for resolution.
- Alert the team when a run fails or conflicts appear.
- *Value:* this is where the manual dependency actually disappears.

### Phase 4 — Field-map UI, and only then consider write-back
- Let a manager map ClickUp custom fields to Digivault fields in the UI instead of
  a JSON blob.
- **Write-back (Digivault → ClickUp) is explicitly out of scope** until 1–3 have
  run in production for a while. Bidirectional sync without a proven conflict
  model is how both systems end up wrong.

---

## 5. Open questions — need answers before Phase 2

1. **Where do clients live in ClickUp?** One List per workspace, or a Folder of
   Lists? Determines whether config is one `list_id` or several.
2. **Ownership call:** per-field provenance (§3.1) or the simpler "ClickUp always
   wins, fields read-only in Digivault"? This is the biggest design fork.
3. **Which ClickUp field is the client's website URL,** and is it reliably filled?
   It drives `_auto_create_website`, so a blank means no site gets provisioned.
4. **Are Departments a ClickUp multi-select or tags?** Digivault stores a JSON
   list validated against six values (`Client.DEPARTMENTS`); the mapper must
   handle unknown incoming values without failing the row.
5. **Does the ClickUp task status vocabulary match** `active/paused/offboarded`, or
   does it need a per-workspace status map?
6. **Sync cadence?** Renewal dates change rarely — hourly is likely plenty, and
   cheaper against the rate limit than every 15 minutes.

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| A bad field map silently corrupts 27 client records | Mandatory dry-run diff in Phase 2; `IntegrationSyncRun` keeps a full before/after audit trail |
| Rate limiting (~100 req/min/token) | Page through one List, cache per run, back off on 429; never per-client API calls |
| Token leakage | Already handled — Fernet-encrypted, `editable=False`, write-only in the serializer. Keep it that way; never log the token or echo it back |
| Sync overwrites a correction someone made in Digivault | The ownership rule in §3.1 — the entire reason it must be decided first |
| Overlapping runs double-writing | Redis lock per team, as `monitors.run_due_checks` already does |
| ClickUp permission change looks like mass deletion | Never auto-delete; mark `orphaned` and surface it |

---

## 7. What this delivers against the original three goals

- **Sync with ClickUp API** — Phases 2–3. Foundation (token, encryption,
  connectivity check, outbound messaging) already exists; the missing pieces are a
  mapping key, a mapper, and a scheduled reconciler.
- **Sync CSM data automatically** — Phase 3. Requires the ownership decision in
  §3.1 to be made first, or automation will fight its users.
- **Reduce manual Excel dependency** — Phase 2 removes the routine need for it.
  **Keep CSV import/export permanently** as a bulk-edit and disaster-recovery
  path; the goal is to stop it being the *only* road in, not to delete it.
