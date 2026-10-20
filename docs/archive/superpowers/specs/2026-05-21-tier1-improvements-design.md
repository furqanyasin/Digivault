# Tier 1 Improvements — Design Spec

**Date:** 2026-05-21  
**Scope:** Three quick-win improvements to existing systems  
**Status:** Approved

---

## A. Monitor Retry Logic + Alert Deduplication

### Problem

The `Monitor` model has a `retry_count` field but `check_single_monitor` ignores it entirely — every single failed check immediately transitions the monitor to "down" and fires a notification. This causes:
- False alerts from transient blips (e.g. a single TCP timeout)
- Duplicate alerts for sustained outages (a new notification fires every check cycle while the monitor stays down)

### Model Changes

Add two fields to `Monitor`:

```python
consecutive_failures = models.PositiveIntegerField(default=0)
is_alerting = models.BooleanField(default=False)
```

Change `retry_count` default from `1` → `3` via migration `default=3`. Existing monitors keep their stored value; new monitors created via UI default to 3 (≈ 90 s with 30 s check interval before alerting).

### Task Logic (`check_single_monitor`)

**On UP result:**
1. If `is_alerting=True`: fire recovery notification, then set `is_alerting=False`.
2. Reset `consecutive_failures=0`.
3. Update `status=up`.

**On DOWN/DEGRADED result:**
1. Increment `consecutive_failures` by 1.
2. Update `status=down/degraded`.
3. If `consecutive_failures >= retry_count` AND `is_alerting=False`: fire down notification, set `is_alerting=True`.
4. Otherwise: no notification (retry in progress, or already alerting).

All three fields (`consecutive_failures`, `is_alerting`, `status`) are updated atomically in a single `Monitor.objects.filter(pk=...).update(...)` call.

### Alert Deduplication

`is_alerting` is the dedup gate. While a monitor is down and `is_alerting=True`, no further down notifications fire regardless of how many checks fail. The recovery notification fires exactly once when the monitor returns to `up`.

### Migration

One migration: add `consecutive_failures` and `is_alerting`, update `retry_count` default to 3.

---

## B. Audit Log Metadata (Previous / New Values)

### Problem

`ActivityLog` records actions but has no structured way to store what changed. "Member role changed" tells you an event happened — it doesn't tell you from `developer` to `manager`. The spec requires `previous_value` / `new_value` tracking.

### Model Change

Add one field to `ActivityLog`:

```python
metadata = models.JSONField(default=dict, blank=True)
```

One migration. No index needed — metadata is display-only, never filtered on.

### Service Change

`AuditService.log()` gains an optional `metadata` parameter:

```python
@staticmethod
def log(..., metadata: dict | None = None) -> None:
```

Passed straight to `ActivityLog.objects.create(metadata=metadata or {})`.

### Callers Updated

| Action | metadata written |
|---|---|
| `TEAM_MEMBER_ROLE_CHANGED` | `{"previous_role": "developer", "new_role": "manager"}` |
| `TEAM_MEMBER_REMOVED` | `{"role": "developer"}` |
| `SETTINGS_TEAM_NAME_CHANGED` | `{"previous_name": "Acme", "new_name": "Acme Ltd"}` |
| `CREDENTIAL_UPDATED` | `{"fields_changed": ["label", "login_url"]}` — field names only, no plaintext credential values |

### Frontend Change

Activity log table (`logs/page.tsx`): when `metadata` is non-empty, render a small grey detail line beneath the description. Format:

- Role change: `developer → manager`
- Team name: `"Acme" → "Acme Ltd"`
- Credential update: `fields changed: label, login_url`
- Member removed: `role: developer`

The serializer already exposes all `ActivityLog` fields. The metadata JSON is passed through as-is; the frontend renders it with a simple switch on `action`.

---

## C. 2FA Manager Disable UI

### Problem

`TotpDisableView` already accepts `user_id` and enforces manager/owner permission server-side, but there is no UI for managers to disable a team member's 2FA. The only disable button lives in Settings and operates on the current user only.

### Backend Change

`TeamMembershipSerializer` does not currently expose whether a member has 2FA enabled. Add a read-only computed field:

```python
totp_enabled = serializers.BooleanField(source="user.totp_enabled", read_only=True)
```

No model change, no migration.

### Frontend Change

In `team-management-client.tsx`, add a `ShieldOff` icon button per member row. Visibility rules (all must be true):

- `canManage` is true (current user is manager or owner)
- `member.totp_enabled === true`
- `member.id !== myMembershipId` (cannot disable own 2FA here — use Settings)
- `canModify` is true (existing role-level guard)

**Interaction:**
1. Click `ShieldOff` button.
2. `window.confirm("Disable 2FA for {name}? They will need to re-enroll on next login.")`.
3. `POST /api/auth/2fa/disable` with `{ user_id: member.user.id }`.
4. On success: optimistically update `member.totp_enabled = false` in local state + toast "2FA disabled for {name}".

A new proxy route `frontend/src/app/api/auth/2fa/disable/route.ts` already exists and forwards to the backend with the auth cookie — no new route needed.

---

## Implementation Order

1. **B first** — model migration + service change + frontend. No task logic affected.
2. **A second** — model migration + task rewrite. Changes the core monitoring loop.
3. **C last** — serializer + frontend only. Purely additive, no risk.
