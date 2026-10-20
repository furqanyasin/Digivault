# Phase 3 — Client Model Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the Client record per client feedback — new statuses (active/paused/offboarded), Tier, website access level, departments, conditional "Other" hosting, domain renewal date, notification toggles; remove Contract/Migration/ClickUp/Comments fields.

**Architecture:** One schema migration (adds + removals) plus a data migration (status `inactive`→`offboarded`; `support_tier` basic/standard/premium → tier bronze/silver/gold). Client-level ClickUp sync is deleted entirely (`apps/clients/services.py`, sync views/urls); the team-level ClickUp alert channel in `apps/monitors` is untouched. CSV import/export columns change accordingly. Frontend forms (new + detail) gain the new fields with tooltips; renewals center swaps Contract for Domain renewal.

**Tech Stack:** Django migration + DRF serializers, Next.js client components.

## Global Constraints

- `pytest --create-db` (model change).
- `npm run build` passes.
- Team-level ClickUp integration (alerts) must keep working — only client-record sync goes.

---

### Task 1: Model + migrations
- Status choices: active / paused / offboarded (data migration maps `inactive`).
- `support_tier` → `tier` (gold/silver/bronze/""), data migration maps premium→gold, standard→silver, basic→bronze.
- Add: `website_access_level` (full_admin/delegate/none/""), `hosting_platform_other` (CharField 100), `departments` (JSONField list of "seo"/"ads"/"dev"/"content"), `domain_renewal_date` (DateField null), `notify_desktop` (bool default True), `notify_email` (bool default True).
- Remove: `migration_status`, `csm_migration_confirmation`, `comments`, `contract_renewal_date`, `clickup_task_id`, `clickup_synced_at` and their choice classes.
- Name stays required; serializer enforces non-blank.

### Task 2: Backend code sweep
- `serializers.py`: new field list; `name` `allow_blank=False`; lookup serializer drops removed fields, status check `!= "active"`.
- `views.py`: delete sync views + ClickUp import keying + migration/CSM/PPC-comment parsing for removed fields; deactivate → `offboarded`; EXPORT_HEADERS = Name, Website URL, Status, Tier, Hosting Platform, Hosting Platform (Other), Hosting Renewal Date, Domain Renewal Date, Website Access Level, Departments, Domain Access, Built by Digi, Maintained by Digi, PPC Ads, Notes.
- Delete `apps/clients/services.py`; remove sync urls.
- Update `tests/clients/*` to the new schema; add tests for status mapping + tier mapping migration helpers and import/export round-trip.

### Task 3: Frontend sweep
- `clients/new/page.tsx` + `client-detail-client.tsx`: remove dropped fields; add Tier select, Website access level select (tooltip), conditional "Other hosting" input, hosting tooltip, departments checkboxes, domain renewal date, Desktop/Email notification toggles; status select (detail only).
- `clients/page.tsx` / `clients-client.tsx`: status filter gains Paused/Offboarded; drop contract column refs.
- `renewals-client.tsx`: Contract section → Domain renewal section.
- `npm run build` green.

### Task 4: Verify
- `pytest --create-db -q` backend green (known pre-existing failures excluded).
- Commit per task.
