# Phase 1 — Close Functional Gaps

**Status:** ⬜ Not started
**Blocks launch:** Items 1–2 partially (decide-or-implement SMS; channel parity).

Finish the half-built features so there are no dead settings or inconsistent behavior.

---

## 1.1 — SMS delivery: implement or remove ⬜

`AlertRule` exposes an SMS channel + `sms_phone_number` with no backend. Pick one.

### Option A — Implement (Twilio or Vonage)
- [ ] Add `SmsDelivery` backend in `apps/alerts/delivery.py`, registered in `get_backend()`.
- [ ] Provider creds via env (`TWILIO_*` / `VONAGE_*`); feature-flag if unset.
- [ ] Retry + failure capture parity with other backends.
- [ ] Phone validation on `AlertRule`.

### Option B — Remove (recommended if SMS isn't day-one critical)
- [ ] Drop SMS choice from `AlertRule.channel`, remove `sms_phone_number`, migration.
- [ ] Remove SMS from frontend alert-rule UI.

### Test plan
- A: mock provider, assert send called + status recorded; failure → FAILED + error.
- B: SMS no longer selectable; existing SMS rules migrated/cleaned.

### Acceptance
✅ No dead SMS settings anywhere in model, API, or UI.

---

## 1.2 — Unify notification channels ⬜

> Monitors use Email+ClickUp; alerts use Email/Slack/In-App. Make one channel abstraction so every module supports Email · Slack · In-App · (SMS if 1.1A).

### Tasks
- [ ] Extract a single `NotificationChannel` concept shared by monitors and alerts (or a common delivery dispatcher).
- [ ] Let monitor notification rules target Slack/In-App.
- [ ] Let alert rules target ClickUp.
- [ ] Backfill/migrate existing `NotificationChannel` + `AlertRule` rows.

### Files
- `apps/alerts/delivery.py`, `apps/alerts/services.py`
- `apps/monitors/notifications.py`, `apps/monitors/models.py`
- migrations for both apps

### Acceptance
✅ Any module can deliver on any channel · existing rules keep working · single delivery code path.

---

## 1.3 — Script monitoring workflow enhancements ⬜

### Tasks
- [ ] Bulk approve / bulk ignore endpoints for scripts.
- [ ] Alert suppression rules (mute a known script/provider per website).
- [ ] Historical script timeline endpoint (per-script change history).

### Files
- `apps/scripts/views.py`, `serializers.py`, `urls.py`, `models.py` (suppression)

### Acceptance
✅ Bulk actions work and are audit-logged · suppressed scripts don't fire alerts · timeline returns ordered history.

---

## 1.4 — Credential management additions ⬜

### Tasks
- [ ] `last_password_changed_at` on `Credential`; set on update.
- [ ] Password strength scoring (zxcvbn-style) surfaced via API.
- [ ] Credential expiry tracking + "expiring credentials" query.

### Files
- `apps/credentials/models.py`, `serializers.py`, `views.py`, migration

### Acceptance
✅ Expiry + strength returned in API · expiring-soon list available for dashboard.

---

## 1.5 — Domain 3-day alert + Renewal Center data ⬜

### Tasks
- [ ] Add **3-day** threshold to `DomainAlert` (currently 90/60/30/14/7).
- [ ] Aggregate endpoint feeding a Renewal Center: domains + SSL + hosting renewals (+ plugin licenses if tracked) with Expiring Soon / Expired / Renewed buckets.

### Files
- `apps/domains/models.py`, `tasks.py`
- new aggregate view (domains or a small `renewals` endpoint)

### Acceptance
✅ 3-day alert fires · single endpoint returns all renewal items bucketed by urgency.

---

## 1.6 — Audit log export & search ⬜

### Tasks
- [ ] Search/filter `ActivityLog` by actor, action, resource, date range.
- [ ] CSV export of filtered logs.
- [ ] Per-user activity report endpoint.

### Files
- `apps/audit/views.py`, `serializers.py`, `urls.py`

### Acceptance
✅ Filterable + exportable logs · user activity report returns scoped results.

---

## Phase 1 exit criteria

- [ ] SMS resolved (implemented or removed)
- [ ] Channel parity across modules
- [ ] Script bulk actions + suppression + timeline
- [ ] Credential expiry/strength
- [ ] Domain 3-day alert + renewal aggregation
- [ ] Audit search/export
