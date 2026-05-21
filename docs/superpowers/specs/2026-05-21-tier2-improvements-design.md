# Tier 2 Improvements — Design Spec

**Date:** 2026-05-21  
**Scope:** Proactive health & alert improvements  
**Status:** Approved

---

## A. Website Health Score (0-100)

### Problem

`Website.status` is a coarse four-value enum (`active/warning/critical/inactive`). The dashboard renders a "health bar" with hardcoded widths (`active → 100%`, `warning → 60%`, `critical → 25%`) — these are fake. There is no numeric signal for how healthy a site actually is, making it impossible to rank or prioritise sites.

### Model Change

Add one field to `Website`:

```python
health_score = models.IntegerField(default=100)
```

One migration. No index needed — used for display only.

### Score Formula

`recalculate_health_score()` instance method on `Website`. Starts at 100, applies deductions, clamps to [0, 100], saves `update_fields=["health_score"]`.

| Condition | Deduction | Cap |
|---|---|---|
| Unacknowledged critical script change | -15 each | max -30 |
| Unacknowledged high script change | -10 each | max -30 |
| Unacknowledged medium script change | -3 each | max -15 |
| Unacknowledged low script change | -1 each | max -5 |
| Domain expires ≤7 days | -20 | — |
| Domain expires ≤30 days (but >7) | -8 | — |
| SSL expires ≤7 days | -20 | — |
| SSL expires ≤14 days (but >7) | -12 | — |
| SSL expires ≤30 days (but >14) | -5 | — |
| Critical vulnerability | -8 each | max -16 |
| High vulnerability | -4 each | max -8 |

Domain/SSL deductions are mutually exclusive (most severe bracket wins). Deductions are summed, then `max(0, min(100, 100 - total))`.

### Recalculation Triggers

`recalculate_health_score()` is called (not signalled — direct call) from:

1. `ScriptChange` post_save signal in `apps/scripts/models.py` (or `apps.scripts` signals module) — only when `is_acknowledged` changes or on new creation
2. Acknowledge endpoint in `apps/scripts/views.py` after setting `is_acknowledged=True`
3. Domain check Celery task in `apps/domains/tasks.py` at the end of `check_domain()`
4. Vulnerability scan completion in `apps/site_health/views.py` `WebsiteSecurityScanView.post()`

### Serializer + API

Add `health_score` to `WebsiteSerializer.fields` as a read-only field. No extra serializer method needed — it's a plain integer column.

### Frontend

`frontend/src/lib/api.ts` `Website` interface: add `health_score: number`.

Dashboard site cards: replace the fake status bar + Badge with a real score display:

```
[Score pill: "87" green / "62" amber / "31" red]  [status badge]
```

Score color thresholds: ≥80 green, 50-79 amber, <50 red.

---

## B. Dashboard Action Center ("Needs Attention")

### Problem

Down monitors, expiring domains/SSLs, and critical script changes live on separate pages. There is no single view that answers "what needs my attention right now?"

### Design

New `NeedsAttention` section in `DashboardPage` (server component). Rendered between the stats row and the high-risk changes section. Hidden entirely when all three categories are empty.

Three categories, each collapsed if empty:

**Down Monitors:** `monitors.filter(m => m.status === "down" || m.status === "degraded")`. Each item shows monitor name, status badge, and a "View" link to `/monitors`. Max 4 shown, then "+ N more →" link.

**Expiring Domains (≤30 days):** Query `Website` objects with `select_related("domain_info")` filtered to `domain_info__expires_at__lte=now+30d` and `domain_info__expires_at__isnull=False`. Each item shows domain name, days remaining (red if ≤7, amber if ≤14), link to `/websites/<id>`. Max 4 shown.

**Expiring SSL Certs (≤14 days):** Same pattern, `domain_info__ssl_expires_at__lte=now+14d`. Days remaining badge. Max 4 shown.

`getData()` adds two extra backend API calls via `Promise.allSettled`:
- `GET /api/v1/websites/expiring-domains/` — new lightweight endpoint
- `GET /api/v1/websites/expiring-ssl/` — new lightweight endpoint

These return `{ id, name, domain, days }[]` — minimal payloads.

### Backend Endpoints

Two new views on the websites router:

```
GET /api/v1/websites/expiring-domains/?days=30
GET /api/v1/websites/expiring-ssl/?days=14
```

Each returns a JSON array of `{id, name, domain, days_until_expiry}`. Filtered to the user's active team, ordered by days ascending.

---

## C. Notification Channel Test Button

### Problem

Users configure email/ClickUp notification channels but have no way to verify they work. A misconfigured channel silently drops alerts.

### Backend

New view: `NotificationChannelTestView` at `POST /api/v1/notification-channels/<pk>/test/`.

Returns:
```json
{"success": true, "message": "Test email sent to jane@acme.com"}
{"success": false, "message": "Failed: <reason>"}
```

Always HTTP 200 (success/failure is in the body, not the status code — the request itself succeeded).

**Email:** Calls `send_mail()` with subject `"[Digivault] Test notification"`, body `"This is a test notification from Digivault. Your email alerts are working correctly."`, to the addresses in `config["addresses"]`.

**ClickUp:** POSTs a task to the configured list using the ClickUp API (`config["api_token"]`, `config["list_id"]`), with name `"[TEST] Digivault notification check — please delete"`. On success, immediately deletes the task. Returns the task name in the success message.

### Frontend Proxy Route

New: `frontend/src/app/api/monitors/channels/[id]/test/route.ts` — forwards `POST` to the backend with the auth cookie.

### Frontend UI

In `NotificationChannelsClient`:
- Add a "Test" button next to each channel's edit/delete buttons.
- On click: set `testing[channelId] = true`, POST to the proxy route, then show an inline result for 3 seconds:
  - Success: green text "Sent ✓"
  - Failure: red text with the error message (truncated to 60 chars)
- The button is disabled while `testing[channelId]` is true.

---

## Implementation Order

1. **A (Health Score)** — model + migration + method + triggers + serializer + API type + frontend cards
2. **B (Action Center)** — two new backend endpoints + frontend section
3. **C (Channel Test)** — backend view + proxy route + frontend button
