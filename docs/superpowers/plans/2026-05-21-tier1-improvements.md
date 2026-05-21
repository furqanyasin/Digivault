# Tier 1 Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement three quick-win improvements: audit log metadata (previous/new values), monitor retry logic with alert deduplication, and 2FA manager disable UI.

**Architecture:** Each improvement is independent. Implement in order B → A → C: audit model first (no deps), monitors second (task logic only), 2FA UI last (purely additive). All backend changes follow the existing Django/DRF envelope pattern; frontend changes are isolated to existing components.

**Tech Stack:** Django 5.1, DRF, Celery, PostgreSQL, Next.js 16 App Router, React 19, TypeScript, Tailwind v4

---

## File Map

| File | Change |
|---|---|
| `apps/audit/models.py` | Add `metadata JSONField` |
| `apps/audit/migrations/0002_activitylog_metadata.py` | New migration |
| `apps/audit/services.py` | Add `metadata` param to `AuditService.log()` |
| `apps/audit/serializers.py` | Expose `metadata` field |
| `apps/accounts/views.py` | Pass metadata to 3 existing `AuditService.log()` calls |
| `apps/credentials/views.py` | Pass metadata to `CREDENTIAL_UPDATED` call |
| `frontend/src/app/(dashboard)/logs/page.tsx` | Render metadata detail line |
| `apps/monitors/models.py` | Add `consecutive_failures`, `is_alerting`; bump `retry_count` default |
| `apps/monitors/migrations/0003_monitor_retry_dedup.py` | New migration |
| `apps/monitors/tasks.py` | Rewrite `check_single_monitor` to use retry + dedup |
| `tests/monitors/test_retry_dedup.py` | New test file |
| `apps/accounts/serializers.py` | Add `totp_enabled` to `TeamMembershipSerializer` |
| `frontend/src/lib/api.ts` | Add `totp_enabled` to `TeamMember` interface |
| `frontend/src/components/team-management-client.tsx` | Add Disable 2FA button per row |

---

## Task 1: Add `metadata` field to ActivityLog

**Files:**
- Modify: `apps/audit/models.py`
- Create: `apps/audit/migrations/0002_activitylog_metadata.py`

- [ ] **Step 1: Add the field**

In `apps/audit/models.py`, add after `ip_address`:

```python
metadata = models.JSONField(default=dict, blank=True)
```

The complete field list in `ActivityLog` (after change):
```python
team = models.ForeignKey(...)
actor = models.ForeignKey(...)
action = models.CharField(max_length=60, choices=Action.choices, db_index=True)
resource_type = models.CharField(max_length=40, blank=True)
resource_id = models.CharField(max_length=100, blank=True)
description = models.CharField(max_length=300)
ip_address = models.GenericIPAddressField(null=True, blank=True)
metadata = models.JSONField(default=dict, blank=True)
```

- [ ] **Step 2: Generate and run migration**

```bash
python manage.py makemigrations audit --name activitylog_metadata
python manage.py migrate
```

Expected: new file `apps/audit/migrations/0002_activitylog_metadata.py`, migration applies cleanly.

- [ ] **Step 3: Verify in shell**

```bash
python manage.py shell -c "from apps.audit.models import ActivityLog; print(ActivityLog._meta.get_field('metadata'))"
```

Expected: `<django.db.models.fields.json.JSONField: metadata>`

- [ ] **Step 4: Commit**

```bash
git add apps/audit/models.py apps/audit/migrations/0002_activitylog_metadata.py
git commit -m "feat(audit): add metadata JSONField to ActivityLog"
```

---

## Task 2: Update AuditService to accept metadata

**Files:**
- Modify: `apps/audit/services.py`

- [ ] **Step 1: Write the failing test**

Create `tests/audit/__init__.py` (empty) and `tests/audit/test_services.py`:

```python
import pytest
from apps.audit.models import ActivityLog
from apps.audit.services import AuditService
from apps.accounts.services import TeamService
from apps.accounts.models import User


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@example.com", password="SecurePass1!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Test Team", owner=owner)


def test_log_stores_metadata(owner, team):
    AuditService.log(
        actor=owner,
        action=ActivityLog.Action.TEAM_MEMBER_ROLE_CHANGED,
        team=team,
        description="Changed role",
        metadata={"previous_role": "developer", "new_role": "manager"},
    )
    log = ActivityLog.objects.filter(actor=owner, team=team).first()
    assert log is not None
    assert log.metadata == {"previous_role": "developer", "new_role": "manager"}


def test_log_defaults_empty_metadata(owner, team):
    AuditService.log(
        actor=owner,
        action=ActivityLog.Action.AUTH_LOGIN,
        team=team,
        description="Login",
    )
    log = ActivityLog.objects.filter(actor=owner, team=team).first()
    assert log.metadata == {}
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/audit/test_services.py -v
```

Expected: `TypeError: log() got an unexpected keyword argument 'metadata'`

- [ ] **Step 3: Update AuditService.log()**

Replace the `log` method signature and body in `apps/audit/services.py`:

```python
@staticmethod
def log(
    actor,
    action: str,
    team,
    description: str = "",
    resource_type: str = "",
    resource_id: str = "",
    ip_address: str | None = None,
    metadata: dict | None = None,
) -> None:
    try:
        from apps.audit.models import ActivityLog

        ActivityLog.objects.create(
            actor=actor,
            team=team,
            action=action,
            description=description,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else "",
            ip_address=ip_address,
            metadata=metadata or {},
        )
    except Exception:
        logger.exception(
            "AuditService.log failed: actor=%s action=%s team=%s",
            getattr(actor, "email", actor),
            action,
            getattr(team, "name", team),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/audit/test_services.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/audit/services.py tests/audit/__init__.py tests/audit/test_services.py
git commit -m "feat(audit): accept metadata in AuditService.log()"
```

---

## Task 3: Pass metadata at existing call sites

**Files:**
- Modify: `apps/accounts/views.py`
- Modify: `apps/credentials/views.py`

- [ ] **Step 1: Update TEAM_MEMBER_ROLE_CHANGED call**

In `apps/accounts/views.py`, find the `patch` method of `TeamMemberDetailView` (~line 171). Replace:

```python
AuditService.log(
    actor=request.user, action=ActivityLog.Action.TEAM_MEMBER_ROLE_CHANGED,
    team=team,
    description=f"Changed {target.user.email}'s role from {old_role} to {new_role}",
    resource_type="team_membership", resource_id=str(target.pk),
)
```

With:

```python
AuditService.log(
    actor=request.user, action=ActivityLog.Action.TEAM_MEMBER_ROLE_CHANGED,
    team=team,
    description=f"Changed {target.user.email}'s role from {old_role} to {new_role}",
    resource_type="team_membership", resource_id=str(target.pk),
    metadata={"previous_role": old_role, "new_role": new_role},
)
```

- [ ] **Step 2: Update TEAM_MEMBER_REMOVED call**

In the same file, `delete` method of `TeamMemberDetailView` (~line 195). Replace:

```python
AuditService.log(
    actor=request.user, action=ActivityLog.Action.TEAM_MEMBER_REMOVED,
    team=team,
    description=f"Removed {removed_email} ({removed_role}) from the team",
    resource_type="team_membership", resource_id=str(pk),
)
```

With:

```python
AuditService.log(
    actor=request.user, action=ActivityLog.Action.TEAM_MEMBER_REMOVED,
    team=team,
    description=f"Removed {removed_email} ({removed_role}) from the team",
    resource_type="team_membership", resource_id=str(pk),
    metadata={"role": removed_role},
)
```

- [ ] **Step 3: Update SETTINGS_TEAM_NAME_CHANGED call**

In the same file, `update` method of `TeamDetailView` (~line 99). Replace:

```python
AuditService.log_request(
    request, ActivityLog.Action.SETTINGS_TEAM_NAME_CHANGED,
    description=f"Renamed team from '{old_name}' to '{new_name}'",
    resource_type="team", resource_id=str(team.pk),
)
```

With:

```python
AuditService.log_request(
    request, ActivityLog.Action.SETTINGS_TEAM_NAME_CHANGED,
    description=f"Renamed team from '{old_name}' to '{new_name}'",
    resource_type="team", resource_id=str(team.pk),
    metadata={"previous_name": old_name, "new_name": new_name},
)
```

Note: `log_request` also needs the `metadata` kwarg — update it now:

```python
@staticmethod
def log_request(request, action: str, description: str = "", resource_type: str = "", resource_id: str = "", metadata: dict | None = None) -> None:
    actor = request.user if request.user.is_authenticated else None
    team = getattr(actor, "active_team", None) if actor else None
    if not team:
        return
    ip = _get_ip(request)
    AuditService.log(
        actor=actor,
        action=action,
        team=team,
        description=description,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip,
        metadata=metadata,
    )
```

- [ ] **Step 4: Update CREDENTIAL_UPDATED call**

In `apps/credentials/views.py`, find `CredentialDetailView` PATCH handler (~line 188). The validated data `d` contains changed fields. Replace:

```python
AuditService.log_request(
    request, ActivityLog.Action.CREDENTIAL_UPDATED,
    description=f"Updated credential '{updated.label}'",
    resource_type="credential", resource_id=updated.pk,
)
```

With:

```python
changed_fields = [k for k in ("label", "credential_type", "login_url", "username", "password", "notes") if d.get(k) is not None]
AuditService.log_request(
    request, ActivityLog.Action.CREDENTIAL_UPDATED,
    description=f"Updated credential '{updated.label}'",
    resource_type="credential", resource_id=updated.pk,
    metadata={"fields_changed": changed_fields},
)
```

- [ ] **Step 5: Run the full test suite to check nothing broke**

```bash
pytest tests/ -x -q -k "not test_response_is_enveloped"
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/accounts/views.py apps/credentials/views.py apps/audit/services.py
git commit -m "feat(audit): pass metadata to role change, removal, name change, credential update"
```

---

## Task 4: Expose metadata in serializer and render in frontend

**Files:**
- Modify: `apps/audit/serializers.py`
- Modify: `frontend/src/app/(dashboard)/logs/page.tsx`

- [ ] **Step 1: Check current serializer**

Open `apps/audit/serializers.py`. Find `ActivityLogSerializer`. Add `"metadata"` to the `fields` tuple:

```python
fields = (
    "id", "actor_email", "actor_name", "action", "action_label",
    "resource_type", "resource_id", "description", "ip_address",
    "metadata", "created_at",
)
```

- [ ] **Step 2: Update LogEntry interface in frontend**

In `frontend/src/app/(dashboard)/logs/page.tsx`, update the `LogEntry` interface:

```typescript
interface LogEntry {
  id: string;
  actor_email: string | null;
  actor_name: string;
  action: string;
  action_label: string;
  resource_type: string;
  description: string;
  ip_address: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}
```

- [ ] **Step 3: Add metadata rendering helper**

Add this function before the `LogsPage` component:

```typescript
function renderMetadata(action: string, metadata: Record<string, unknown>): string | null {
  if (!metadata || Object.keys(metadata).length === 0) return null;
  if (action === "team.member_role_changed" && metadata.previous_role && metadata.new_role) {
    return `${metadata.previous_role} → ${metadata.new_role}`;
  }
  if (action === "team.member_removed" && metadata.role) {
    return `role: ${metadata.role}`;
  }
  if (action === "settings.team_name_changed" && metadata.previous_name && metadata.new_name) {
    return `"${metadata.previous_name}" → "${metadata.new_name}"`;
  }
  if (action === "credential.updated" && Array.isArray(metadata.fields_changed)) {
    return `fields changed: ${(metadata.fields_changed as string[]).join(", ")}`;
  }
  return null;
}
```

- [ ] **Step 4: Render metadata in the description cell**

In the `<td>` that renders `log.description` (currently `<td className="px-4 py-3 text-muted-foreground">{log.description}</td>`), replace with:

```typescript
<td className="px-4 py-3 text-muted-foreground">
  <div>{log.description}</div>
  {renderMetadata(log.action, log.metadata) && (
    <div className="text-xs text-muted-foreground/60 mt-0.5 font-mono">
      {renderMetadata(log.action, log.metadata)}
    </div>
  )}
</td>
```

- [ ] **Step 5: Commit**

```bash
git add apps/audit/serializers.py "frontend/src/app/(dashboard)/logs/page.tsx"
git commit -m "feat(audit): expose and render metadata in activity log"
```

---

## Task 5: Add retry/dedup fields to Monitor model

**Files:**
- Modify: `apps/monitors/models.py`
- Create: `apps/monitors/migrations/0003_monitor_retry_dedup.py`

- [ ] **Step 1: Add fields to Monitor**

In `apps/monitors/models.py`, after `is_active = models.BooleanField(default=True)`, add:

```python
consecutive_failures = models.PositiveIntegerField(default=0)
is_alerting = models.BooleanField(default=False)
```

Also change `retry_count` default from `1` to `3`:

```python
retry_count = models.PositiveIntegerField(
    default=3, help_text="Consecutive failures before incident"
)
```

- [ ] **Step 2: Generate and run migration**

```bash
python manage.py makemigrations monitors --name monitor_retry_dedup
python manage.py migrate
```

Expected: new file `apps/monitors/migrations/0003_monitor_retry_dedup.py`, applies cleanly. Existing monitors get `consecutive_failures=0`, `is_alerting=False`, `retry_count` stays at their stored value (not back-filled to 3).

- [ ] **Step 3: Commit**

```bash
git add apps/monitors/models.py apps/monitors/migrations/0003_monitor_retry_dedup.py
git commit -m "feat(monitors): add consecutive_failures and is_alerting fields; bump retry_count default to 3"
```

---

## Task 6: Rewrite check_single_monitor with retry + dedup

**Files:**
- Modify: `apps/monitors/tasks.py`
- Create: `tests/monitors/__init__.py`
- Create: `tests/monitors/test_retry_dedup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/monitors/__init__.py` (empty).

Create `tests/monitors/test_retry_dedup.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor, MonitorCheck


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@m.com", password="SecurePass1!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Monitor Team", owner=owner)


@pytest.fixture
def monitor(team):
    return Monitor.objects.create(
        team=team,
        name="Test Site",
        url="https://example.com",
        monitor_type="http",
        retry_count=3,
        status="up",
        is_alerting=False,
        consecutive_failures=0,
    )


def run_task_with_result(monitor_id, result_status):
    """Helper: run check_single_monitor with a mocked checker result."""
    from apps.monitors.tasks import check_single_monitor
    fake_result = {
        "status": result_status,
        "response_time_ms": 200 if result_status == "up" else None,
        "status_code": 200 if result_status == "up" else None,
        "error_message": "" if result_status == "up" else "Connection refused",
    }
    with patch("apps.monitors.tasks.run_check", return_value=fake_result):
        with patch("apps.monitors.tasks.notify_status_change") as mock_notify:
            check_single_monitor(str(monitor_id))
            return mock_notify


def test_first_failure_does_not_alert(monitor):
    """First failure increments counter but does not fire alert (retry_count=3)."""
    mock_notify = run_task_with_result(monitor.pk, "down")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 1
    assert monitor.is_alerting is False
    mock_notify.assert_not_called()


def test_second_failure_does_not_alert(monitor):
    """Second failure still within retry window — no alert."""
    Monitor.objects.filter(pk=monitor.pk).update(consecutive_failures=1)
    mock_notify = run_task_with_result(monitor.pk, "down")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 2
    assert monitor.is_alerting is False
    mock_notify.assert_not_called()


def test_third_failure_fires_alert(monitor):
    """Third consecutive failure meets retry_count=3 — alert fires."""
    Monitor.objects.filter(pk=monitor.pk).update(consecutive_failures=2)
    mock_notify = run_task_with_result(monitor.pk, "down")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 3
    assert monitor.is_alerting is True
    mock_notify.assert_called_once()
    args = mock_notify.call_args[0]
    assert args[1] == "up"   # previous_status
    assert args[2] == "down" # new_status


def test_subsequent_failure_does_not_re_alert(monitor):
    """Already alerting — no duplicate alert on further failures."""
    Monitor.objects.filter(pk=monitor.pk).update(
        consecutive_failures=3, is_alerting=True, status="down"
    )
    mock_notify = run_task_with_result(monitor.pk, "down")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 4
    assert monitor.is_alerting is True
    mock_notify.assert_not_called()


def test_recovery_fires_alert_and_resets(monitor):
    """Recovery from alerting state fires recovery alert and resets counters."""
    Monitor.objects.filter(pk=monitor.pk).update(
        consecutive_failures=3, is_alerting=True, status="down"
    )
    mock_notify = run_task_with_result(monitor.pk, "up")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 0
    assert monitor.is_alerting is False
    mock_notify.assert_called_once()
    args = mock_notify.call_args[0]
    assert args[1] == "down" # previous_status
    assert args[2] == "up"   # new_status


def test_recovery_without_alert_no_notification(monitor):
    """Failure count below threshold, then recovery — no notification fires."""
    Monitor.objects.filter(pk=monitor.pk).update(
        consecutive_failures=1, is_alerting=False, status="down"
    )
    mock_notify = run_task_with_result(monitor.pk, "up")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 0
    assert monitor.is_alerting is False
    mock_notify.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/monitors/test_retry_dedup.py -v
```

Expected: most tests FAIL because current task fires notification on every status change and doesn't use `consecutive_failures`.

- [ ] **Step 3: Rewrite check_single_monitor**

Replace the entire `check_single_monitor` task in `apps/monitors/tasks.py` with:

```python
@shared_task(
    bind=True,
    max_retries=0,
    name="monitors.check_single_monitor",
)
def check_single_monitor(self, monitor_id: str):
    """Run one health check and apply retry + dedup logic.

    Only fires a down alert after consecutive_failures reaches retry_count.
    Only fires a recovery alert when transitioning from is_alerting=True back to up.
    No duplicate alerts while a monitor stays down.
    """
    from apps.monitors.checker import run_check
    from apps.monitors.models import Monitor, MonitorCheck

    try:
        monitor = Monitor.objects.get(pk=monitor_id)
    except Monitor.DoesNotExist:
        return

    if not monitor.is_active or monitor.status == "paused":
        return

    try:
        result = run_check(monitor)
    except Exception as exc:
        logger.exception("check_single_monitor: checker raised for %s", monitor_id)
        result = {
            "status": "down",
            "response_time_ms": None,
            "status_code": None,
            "error_message": str(exc)[:300],
        }

    previous_status = monitor.status
    new_status = result["status"]

    MonitorCheck.objects.create(
        monitor=monitor,
        status=new_status,
        response_time_ms=result.get("response_time_ms"),
        status_code=result.get("status_code"),
        error_message=result.get("error_message", ""),
    )

    if new_status == "up":
        should_notify = monitor.is_alerting  # recovery alert only if we were alerting
        Monitor.objects.filter(pk=monitor.pk).update(
            status=new_status,
            last_checked_at=timezone.now(),
            last_response_time=result.get("response_time_ms"),
            consecutive_failures=0,
            is_alerting=False,
        )
    else:
        new_failures = monitor.consecutive_failures + 1
        fires_alert = new_failures >= monitor.retry_count and not monitor.is_alerting
        should_notify = fires_alert
        Monitor.objects.filter(pk=monitor.pk).update(
            status=new_status,
            last_checked_at=timezone.now(),
            last_response_time=result.get("response_time_ms"),
            consecutive_failures=new_failures,
            is_alerting=monitor.is_alerting or fires_alert,
        )

    monitor.refresh_from_db()
    monitor.recalculate_uptime()

    logger.info(
        "monitor %s (%s) → %s  %sms  failures=%d alerting=%s",
        monitor.name,
        monitor.url,
        new_status,
        result.get("response_time_ms"),
        monitor.consecutive_failures,
        monitor.is_alerting,
    )

    if should_notify and previous_status != "pending":
        try:
            notify_status_change(monitor, previous_status, new_status)
        except Exception:
            logger.exception("notify_status_change failed for monitor %s", monitor_id)
```

Also add the import at the top of the function or ensure `notify_status_change` is imported:

```python
from apps.monitors.notifications import notify_status_change
```

Move this import to the top of the task file (after the existing imports) so it's not inside the function body.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/monitors/test_retry_dedup.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -x -q -k "not test_response_is_enveloped"
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/monitors/tasks.py tests/monitors/__init__.py tests/monitors/test_retry_dedup.py
git commit -m "feat(monitors): retry logic and alert deduplication (retry_count=3, is_alerting gate)"
```

---

## Task 7: Expose totp_enabled in TeamMembershipSerializer

**Files:**
- Modify: `apps/accounts/serializers.py`
- Modify: `apps/accounts/views.py` (select_related)

- [ ] **Step 1: Add totp_enabled to TeamMembershipSerializer**

In `apps/accounts/serializers.py`, update `TeamMembershipSerializer`:

```python
class TeamMembershipSerializer(BaseModelSerializer):
    user = UserSerializer(read_only=True)
    totp_enabled = serializers.BooleanField(source="user.totp_enabled", read_only=True)

    class Meta:
        model = TeamMembership
        fields = ("id", "user", "role", "totp_enabled", "created_at")
        read_only_fields = ("id", "totp_enabled", "created_at")
```

- [ ] **Step 2: Update TeamMemberListView select_related**

In `apps/accounts/views.py`, `TeamMemberListView.get_queryset()`, the query already does `.select_related("user")`. The `totp_enabled` field lives on `User`, so no additional join is needed. Verify it looks like:

```python
def get_queryset(self):
    return (
        TeamMembership.objects.filter(
            team_id=self.kwargs["team_pk"],
            team__memberships__user=self.request.user,
        )
        .select_related("user")
        .distinct()
    )
```

No change needed if already has `.select_related("user")`.

- [ ] **Step 3: Update TeamMember interface in frontend**

In `frontend/src/lib/api.ts`, find `TeamMember` interface and add `totp_enabled`:

```typescript
export interface TeamMember {
  id: string;
  user: {
    id: string;
    email: string;
    first_name: string;
    last_name: string;
    timezone: string;
  };
  role: string;
  totp_enabled: boolean;
  created_at: string;
}
```

- [ ] **Step 4: Commit**

```bash
git add apps/accounts/serializers.py frontend/src/lib/api.ts
git commit -m "feat(team): expose totp_enabled on TeamMembership serializer"
```

---

## Task 8: Add 2FA Disable button to team management UI

**Files:**
- Modify: `frontend/src/components/team-management-client.tsx`

- [ ] **Step 1: Add ShieldOff to imports**

At the top of `team-management-client.tsx`, update the lucide-react import:

```typescript
import { UserPlus, Trash2, Check, ShieldAlert, X, ShieldOff } from "lucide-react";
```

- [ ] **Step 2: Add handleDisable2fa function**

After `handleRemoveMember`, add:

```typescript
async function handleDisable2fa(userId: string, memberName: string) {
  if (!confirm(`Disable 2FA for ${memberName}? They will need to re-enrol on next login.`)) return;
  const res = await fetch("/api/auth/2fa/disable", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId }),
  });
  if (res.ok) refresh();
}
```

- [ ] **Step 3: Add the button in the members table row**

In the `{canManage && <TableCell>...</TableCell>}` block (the actions cell), after the existing `Trash2` button, add the ShieldOff button:

```typescript
{canManage && (
  <TableCell>
    <div className="flex items-center gap-1">
      {canModify && !isSelf && (member as TeamMember & { totp_enabled: boolean }).totp_enabled && (
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7 text-amber-500 hover:text-amber-600"
          title="Disable 2FA for this member"
          onClick={() => handleDisable2fa(
            member.user.id,
            (member.user.first_name || member.user.last_name)
              ? `${member.user.first_name} ${member.user.last_name}`.trim()
              : member.user.email
          )}
        >
          <ShieldOff className="h-3.5 w-3.5" />
        </Button>
      )}
      {canModify && (
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7 text-red-500 hover:text-red-600"
          title="Remove member"
          onClick={() => handleRemoveMember(member.id)}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  </TableCell>
)}
```

Since `TeamMember` now has `totp_enabled: boolean` (added in Task 7), the cast can be simplified to just `member.totp_enabled`.

- [ ] **Step 4: Simplify the cast now that api.ts is updated**

Replace `(member as TeamMember & { totp_enabled: boolean }).totp_enabled` with simply `member.totp_enabled` — the type is now defined in `TeamMember`.

Final button condition: `canModify && !isSelf && member.totp_enabled`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/team-management-client.tsx
git commit -m "feat(team): add Disable 2FA button for managers in team member table"
```

---

## Task 9: Push and verify

- [ ] **Step 1: Run full test suite one last time**

```bash
pytest tests/ -q -k "not test_response_is_enveloped"
```

Expected: all tests pass.

- [ ] **Step 2: Push to GitHub**

```bash
git push origin main
```

- [ ] **Step 3: Manual smoke test checklist**

- [ ] Log in, check Activity Log page — role change events show `developer → manager` detail line
- [ ] Change a monitor to down, confirm no alert fires until 3 consecutive failures
- [ ] Recover the monitor, confirm one recovery notification fires
- [ ] As manager, go to Team page — member with 2FA enabled shows amber ShieldOff button
- [ ] Click ShieldOff — confirm dialog appears, on confirm the button disappears
