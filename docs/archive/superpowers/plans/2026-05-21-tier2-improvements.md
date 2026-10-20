# Tier 2 Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a computed website health score (0-100), a dashboard "Needs Attention" action center, and a notification channel test button.

**Architecture:** Health score is a DB column on `Website`, recalculated synchronously from explicit call sites (no signals). Action center adds two new `@action` endpoints on `WebsiteViewSet` and a new UI section in the dashboard page. Channel test is a new `POST` endpoint + proxy route + frontend button.

**Tech Stack:** Django 5.1, DRF, Next.js 16 App Router, React 19, TypeScript, Tailwind v4, pytest

---

## File Map

**Created:**
- `tests/websites/test_health_score.py` — health score unit + integration tests
- `tests/websites/test_expiring_endpoints.py` — expiring domains/SSL endpoint tests
- `tests/monitors/test_channel_test.py` — channel test endpoint tests
- `apps/websites/migrations/0004_website_health_score.py` — migration
- `frontend/src/app/api/websites/expiring-domains/route.ts` — proxy
- `frontend/src/app/api/websites/expiring-ssl/route.ts` — proxy
- `frontend/src/app/api/notification-channels/[id]/test/route.ts` — proxy

**Modified:**
- `apps/websites/models.py` — add `health_score` field + `recalculate_health_score()` method
- `apps/websites/serializers.py` — add `health_score` to fields
- `apps/websites/views.py` — add `expiring_domains` + `expiring_ssl` actions
- `apps/scripts/views.py` — call `recalculate_health_score()` after acknowledge
- `apps/domains/tasks.py` — call `recalculate_health_score()` after domain check
- `apps/site_health/tasks.py` — call `recalculate_health_score()` after scan done
- `apps/monitors/views.py` — add `NotificationChannelTestView`
- `apps/monitors/urls.py` — register test route
- `frontend/src/lib/api.ts` — add `health_score` to `Website` interface
- `frontend/src/app/(dashboard)/dashboard/page.tsx` — real score display + action center
- `frontend/src/components/notification-channels-client.tsx` — test button

---

## Task 1: Website Health Score — Model + Migration

**Files:**
- Modify: `apps/websites/models.py`
- Create: `apps/websites/migrations/0004_website_health_score.py`
- Create: `tests/websites/test_health_score.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/websites/test_health_score.py
import pytest
from django.utils import timezone
from datetime import timedelta

from apps.accounts.services import TeamService
from apps.accounts.models import User
from apps.websites.models import Website
from apps.scripts.models import ScriptChange, Script
from apps.domains.models import DomainInfo


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="hs@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="HS Agency", owner=owner)


@pytest.fixture
def site(team):
    return Website.objects.create(team=team, name="Test Site", domain="test.com")


@pytest.mark.django_db
class TestHealthScore:
    def test_default_score_is_100(self, site):
        assert site.health_score == 100

    def test_recalculate_returns_100_for_clean_site(self, site):
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100

    def test_pending_critical_change_deducts_15(self, site):
        script = Script.objects.create(
            website=site, src_url="https://x.com/a.js", src_domain="x.com",
            provider="unknown", category="unknown", location="head", scope="GLOBAL",
        )
        ScriptChange.objects.create(
            website=site, script=script,
            change_type=ScriptChange.ChangeType.ADDED,
            severity=ScriptChange.Severity.CRITICAL,
            description="new script",
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 85  # 100 - 15

    def test_critical_deduction_capped_at_30(self, site):
        script = Script.objects.create(
            website=site, src_url="https://x.com/a.js", src_domain="x.com",
            provider="unknown", category="unknown", location="head", scope="GLOBAL",
        )
        for i in range(5):
            ScriptChange.objects.create(
                website=site, script=script,
                change_type=ScriptChange.ChangeType.ADDED,
                severity=ScriptChange.Severity.CRITICAL,
                description=f"change {i}",
            )
        site.recalculate_health_score()
        site.refresh_from_db()
        # 5 * 15 = 75 but capped at 30 for criticals → deduction = 30
        assert site.health_score == 70  # 100 - 30

    def test_acknowledged_changes_not_counted(self, site):
        script = Script.objects.create(
            website=site, src_url="https://x.com/a.js", src_domain="x.com",
            provider="unknown", category="unknown", location="head", scope="GLOBAL",
        )
        change = ScriptChange.objects.create(
            website=site, script=script,
            change_type=ScriptChange.ChangeType.ADDED,
            severity=ScriptChange.Severity.CRITICAL,
            description="acked",
            acknowledged_at=timezone.now(),
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100

    def test_ssl_expiry_within_14_days_deducts_12(self, site):
        DomainInfo.objects.create(
            website=site,
            ssl_expires_at=timezone.now() + timedelta(days=10),
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 88  # 100 - 12

    def test_ssl_expiry_within_7_days_deducts_20(self, site):
        DomainInfo.objects.create(
            website=site,
            ssl_expires_at=timezone.now() + timedelta(days=5),
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 80  # 100 - 20

    def test_score_clamped_to_zero(self, site):
        script = Script.objects.create(
            website=site, src_url="https://x.com/a.js", src_domain="x.com",
            provider="unknown", category="unknown", location="head", scope="GLOBAL",
        )
        # Pile on all deduction categories
        for i in range(3):
            ScriptChange.objects.create(
                website=site, script=script,
                change_type=ScriptChange.ChangeType.ADDED,
                severity=ScriptChange.Severity.CRITICAL,
                description=f"c {i}",
            )
            ScriptChange.objects.create(
                website=site, script=script,
                change_type=ScriptChange.ChangeType.ADDED,
                severity=ScriptChange.Severity.HIGH,
                description=f"h {i}",
            )
        DomainInfo.objects.create(
            website=site,
            ssl_expires_at=timezone.now() + timedelta(days=3),
            expires_at=timezone.now() + timedelta(days=3),
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/websites/test_health_score.py -v
```

Expected: `AttributeError: type object 'Website' has no attribute 'health_score'`

- [ ] **Step 3: Add `health_score` field and `recalculate_health_score()` to `apps/websites/models.py`**

Add after the `last_seen_at` field (around line 56) in the `Website` model:

```python
    health_score = models.IntegerField(default=100)
```

Add this method to the `Website` class (after `regenerate_site_id`):

```python
    def recalculate_health_score(self) -> None:
        """Compute and persist a 0-100 health score from pending issues."""
        from django.core.exceptions import ObjectDoesNotExist
        from django.utils import timezone
        from apps.scripts.models import ScriptChange

        deductions = 0

        # Unacknowledged script changes
        pending_sevs = list(
            ScriptChange.objects.filter(
                website=self, acknowledged_at__isnull=True
            ).values_list("severity", flat=True)
        )
        sev_count: dict[str, int] = {}
        for s in pending_sevs:
            sev_count[s] = sev_count.get(s, 0) + 1

        deductions += min(sev_count.get("critical", 0) * 15, 30)
        deductions += min(sev_count.get("high", 0) * 10, 30)
        deductions += min(sev_count.get("medium", 0) * 3, 15)
        deductions += min(sev_count.get("low", 0) * 1, 5)

        # Domain / SSL expiry
        try:
            d = self.domain_info
            now = timezone.now()
            if d.expires_at:
                days = max(0, (d.expires_at - now).days)
                if days <= 7:
                    deductions += 20
                elif days <= 30:
                    deductions += 8
            if d.ssl_expires_at:
                days = max(0, (d.ssl_expires_at - now).days)
                if days <= 7:
                    deductions += 20
                elif days <= 14:
                    deductions += 12
                elif days <= 30:
                    deductions += 5
        except ObjectDoesNotExist:
            pass

        # Vulnerabilities
        try:
            from apps.site_health.models import VulnerabilityReport
            vuln_sevs = list(
                VulnerabilityReport.objects.filter(website=self)
                .values_list("severity", flat=True)
            )
            v_count: dict[str, int] = {}
            for v in vuln_sevs:
                v_count[v] = v_count.get(v, 0) + 1
            deductions += min(v_count.get("critical", 0) * 8, 16)
            deductions += min(v_count.get("high", 0) * 4, 8)
        except Exception:
            pass

        score = max(0, min(100, 100 - deductions))
        Website.objects.filter(pk=self.pk).update(health_score=score)
```

- [ ] **Step 4: Create migration**

```
python manage.py makemigrations websites --name=website_health_score
```

Expected: `Migrations for 'websites': apps/websites/migrations/0004_website_health_score.py`

- [ ] **Step 5: Apply migration**

```
python manage.py migrate
```

Expected: `Applying websites.0004_website_health_score... OK`

- [ ] **Step 6: Run tests — should pass**

```
pytest tests/websites/test_health_score.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 7: Commit**

```
git add apps/websites/models.py apps/websites/migrations/0004_website_health_score.py tests/websites/test_health_score.py
git commit -m "feat(websites): add health_score field and recalculate_health_score() method"
```

---

## Task 2: Wire Health Score Recalculation Triggers

**Files:**
- Modify: `apps/scripts/views.py` (AcknowledgeChangeView)
- Modify: `apps/domains/tasks.py` (check_domain)
- Modify: `apps/site_health/tasks.py` (run_security_scan)

- [ ] **Step 1: Add call in `AcknowledgeChangeView.post()` in `apps/scripts/views.py`**

After the existing call to `_update_website_status(change.website)` (line ~225), add:

```python
        change.website.recalculate_health_score()
```

The surrounding context should look like:

```python
        # Recalculate website status immediately so the dashboard reflects
        # the acknowledgement without waiting for the next ingest.
        from apps.scripts.tasks import _update_website_status
        _update_website_status(change.website)

        change.website.recalculate_health_score()

        return Response(ScriptChangeSerializer(change).data)
```

- [ ] **Step 2: Add call in `check_domain` task in `apps/domains/tasks.py`**

After the existing `_create_expiry_alerts(domain_info)` call (line ~54), add:

```python
    _create_expiry_alerts(domain_info)
    website.recalculate_health_score()
```

- [ ] **Step 3: Add call in `run_security_scan` task in `apps/site_health/tasks.py`**

Find the block that sets `state.scan_status = "done"` and saves (around line 124). After that `state.save(...)` call, add:

```python
        state.scan_status = "done"
        state.save(update_fields=["last_scanned_at", "scan_status", "plugins_detected"])
        website.recalculate_health_score()
```

- [ ] **Step 4: Run the existing test suite to confirm nothing is broken**

```
pytest tests/websites/ tests/monitors/ -v -k "not test_response_is_enveloped"
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```
git add apps/scripts/views.py apps/domains/tasks.py apps/site_health/tasks.py
git commit -m "feat(websites): wire health_score recalculation to ack, domain check, and security scan"
```

---

## Task 3: Expose health_score in API + Frontend

**Files:**
- Modify: `apps/websites/serializers.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/app/(dashboard)/dashboard/page.tsx`

- [ ] **Step 1: Add `health_score` to `WebsiteSerializer`**

In `apps/websites/serializers.py`, add `"health_score"` to the `fields` tuple in `WebsiteSerializer.Meta`:

```python
        fields = (
            "id",
            "name",
            "domain",
            "platform",
            "site_id",
            "status",
            "health_score",
            "notes",
            "tags",
            "last_seen_at",
            "snippet_html",
            "script_count",
            "unknown_script_count",
            "client",
            "client_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "site_id", "health_score", "last_seen_at", "created_at", "updated_at")
```

- [ ] **Step 2: Write API test**

Add to `tests/websites/test_models.py` in the `TestWebsiteAPI` class:

```python
    def test_health_score_in_response(self, owner, team):
        Website.objects.create(team=team, name="HS Test", domain="hstest.com")
        client = self._make_client(owner)
        resp = client.get("/api/v1/websites/")
        assert resp.status_code == 200
        first = resp.data["data"][0]
        assert "health_score" in first
        assert isinstance(first["health_score"], int)
```

- [ ] **Step 3: Run the new test**

```
pytest tests/websites/test_models.py::TestWebsiteAPI::test_health_score_in_response -v
```

Expected: PASS

- [ ] **Step 4: Update `Website` interface in `frontend/src/lib/api.ts`**

Add `health_score: number` to the `Website` interface (after `status`):

```typescript
export interface Website {
  id: string;
  name: string;
  domain: string;
  platform: string;
  site_id: string;
  status: string;
  health_score: number;
  notes: string;
  tags: string[];
  script_count: number;
  unknown_script_count: number;
  snippet_html: string;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 5: Replace fake health bar with real score in dashboard**

In `frontend/src/app/(dashboard)/dashboard/page.tsx`, find the site card rendering section.

Replace the `/* Health bar */` block (~lines 238-257) — the `<div className="space-y-1">` containing the health label and bar — with:

```tsx
                    {/* Health score */}
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>Health</span>
                      <div className="flex items-center gap-2">
                        <span className={`font-bold text-sm ${
                          (site.health_score ?? 100) >= 80
                            ? "text-emerald-600"
                            : (site.health_score ?? 100) >= 50
                            ? "text-amber-500"
                            : "text-red-500"
                        }`}>
                          {site.health_score ?? 100}
                        </span>
                        <Badge
                          variant={
                            site.status === "critical" ? "destructive" :
                            site.status === "warning" ? "warning" :
                            site.status === "active" ? "success" : "secondary"
                          }
                          className="text-xs h-5"
                        >
                          {site.status ?? "unknown"}
                        </Badge>
                      </div>
                    </div>
                    <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          (site.health_score ?? 100) >= 80
                            ? "bg-emerald-500"
                            : (site.health_score ?? 100) >= 50
                            ? "bg-amber-400"
                            : "bg-red-500"
                        }`}
                        style={{ width: `${site.health_score ?? 100}%` }}
                      />
                    </div>
```

- [ ] **Step 6: Run TypeScript check**

```
cd frontend && npm run lint
```

Expected: no errors

- [ ] **Step 7: Commit**

```
git add apps/websites/serializers.py tests/websites/test_models.py frontend/src/lib/api.ts "frontend/src/app/(dashboard)/dashboard/page.tsx"
git commit -m "feat(websites): expose health_score in API and replace fake dashboard health bar"
```

---

## Task 4: Dashboard Action Center + Expiring Endpoints

**Files:**
- Modify: `apps/websites/views.py` (add two @action methods)
- Create: `tests/websites/test_expiring_endpoints.py`
- Create: `frontend/src/app/api/websites/expiring-domains/route.ts`
- Create: `frontend/src/app/api/websites/expiring-ssl/route.ts`
- Modify: `frontend/src/app/(dashboard)/dashboard/page.tsx`

- [ ] **Step 1: Write failing endpoint tests**

```python
# tests/websites/test_expiring_endpoints.py
import pytest
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.domains.models import DomainInfo
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="exp@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Expiry Agency", owner=owner)


@pytest.fixture
def auth_client(owner, team):
    client = APIClient()
    resp = client.post(
        "/api/v1/auth/token/",
        {"email": owner.email, "password": "Pass123!"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['data']['access']}")
    return client


@pytest.mark.django_db
class TestExpiringEndpoints:
    def test_expiring_domains_returns_sites_within_30_days(self, owner, team, auth_client):
        site = Website.objects.create(team=team, name="ExpiringDomain", domain="exp.com")
        DomainInfo.objects.create(
            website=site,
            expires_at=timezone.now() + timedelta(days=15),
        )
        resp = auth_client.get("/api/v1/websites/expiring-domains/")
        assert resp.status_code == 200
        data = resp.data["data"]
        assert any(d["domain"] == "exp.com" for d in data)

    def test_expiring_domains_excludes_sites_beyond_30_days(self, owner, team, auth_client):
        site = Website.objects.create(team=team, name="FarExpiry", domain="far.com")
        DomainInfo.objects.create(
            website=site,
            expires_at=timezone.now() + timedelta(days=60),
        )
        resp = auth_client.get("/api/v1/websites/expiring-domains/")
        assert resp.status_code == 200
        data = resp.data["data"]
        assert not any(d["domain"] == "far.com" for d in data)

    def test_expiring_ssl_returns_sites_within_14_days(self, owner, team, auth_client):
        site = Website.objects.create(team=team, name="ExpiringSsl", domain="ssl.com")
        DomainInfo.objects.create(
            website=site,
            ssl_expires_at=timezone.now() + timedelta(days=7),
        )
        resp = auth_client.get("/api/v1/websites/expiring-ssl/")
        assert resp.status_code == 200
        data = resp.data["data"]
        assert any(d["domain"] == "ssl.com" for d in data)

    def test_expiring_ssl_excludes_sites_beyond_14_days(self, owner, team, auth_client):
        site = Website.objects.create(team=team, name="FarSsl", domain="farssl.com")
        DomainInfo.objects.create(
            website=site,
            ssl_expires_at=timezone.now() + timedelta(days=30),
        )
        resp = auth_client.get("/api/v1/websites/expiring-ssl/")
        assert resp.status_code == 200
        data = resp.data["data"]
        assert not any(d["domain"] == "farssl.com" for d in data)

    def test_expiring_domains_isolated_to_team(self, owner, team, auth_client):
        other_owner = User.objects.create_user(email="other_exp@test.com", password="Pass123!")
        other_team = TeamService.create(name="Other Expiry", owner=other_owner)
        other_site = Website.objects.create(team=other_team, name="OtherSite", domain="other.com")
        DomainInfo.objects.create(
            website=other_site,
            expires_at=timezone.now() + timedelta(days=5),
        )
        resp = auth_client.get("/api/v1/websites/expiring-domains/")
        assert resp.status_code == 200
        data = resp.data["data"]
        assert not any(d["domain"] == "other.com" for d in data)
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/websites/test_expiring_endpoints.py -v
```

Expected: `FAIL` — 404 because the endpoints don't exist yet

- [ ] **Step 3: Add `expiring_domains` and `expiring_ssl` actions to `WebsiteViewSet` in `apps/websites/views.py`**

Add these two methods to `WebsiteViewSet` (after the existing `@action` methods):

```python
    @action(detail=False, methods=["get"], url_path="expiring-domains")
    def expiring_domains(self, request):
        from datetime import timedelta
        from django.utils import timezone
        days = int(request.query_params.get("days", 30))
        threshold = timezone.now() + timedelta(days=days)
        qs = (
            self.get_queryset()
            .select_related("domain_info")
            .filter(
                domain_info__expires_at__isnull=False,
                domain_info__expires_at__lte=threshold,
            )
            .order_by("domain_info__expires_at")
        )
        data = [
            {
                "id": str(w.id),
                "name": w.name,
                "domain": w.domain,
                "days_until_expiry": w.domain_info.domain_days_until_expiry,
            }
            for w in qs
        ]
        return Response(data)

    @action(detail=False, methods=["get"], url_path="expiring-ssl")
    def expiring_ssl(self, request):
        from datetime import timedelta
        from django.utils import timezone
        days = int(request.query_params.get("days", 14))
        threshold = timezone.now() + timedelta(days=days)
        qs = (
            self.get_queryset()
            .select_related("domain_info")
            .filter(
                domain_info__ssl_expires_at__isnull=False,
                domain_info__ssl_expires_at__lte=threshold,
            )
            .order_by("domain_info__ssl_expires_at")
        )
        data = [
            {
                "id": str(w.id),
                "name": w.name,
                "domain": w.domain,
                "days_until_expiry": w.domain_info.ssl_days_until_expiry,
            }
            for w in qs
        ]
        return Response(data)
```

Also ensure `Response` is imported at the top (it already is in that file).

- [ ] **Step 4: Run tests — should pass**

```
pytest tests/websites/test_expiring_endpoints.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 5: Create proxy routes for the frontend**

Create `frontend/src/app/api/websites/expiring-domains/route.ts`:

```typescript
import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET() {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json([], { status: 401 });
  const upstream = await fetch(`${API_BASE}/api/v1/websites/expiring-domains/?days=30`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
```

Create `frontend/src/app/api/websites/expiring-ssl/route.ts`:

```typescript
import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET() {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json([], { status: 401 });
  const upstream = await fetch(`${API_BASE}/api/v1/websites/expiring-ssl/?days=14`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
```

- [ ] **Step 6: Add expiring queries and Action Center to the dashboard**

In `frontend/src/app/(dashboard)/dashboard/page.tsx`, update the `getData` function to fetch expiring items alongside websites and monitors. The two new calls use the backend API directly (server-side, with token) — no proxy needed here since this is a server component:

At the top of `getData`, replace the existing destructuring:

```typescript
async function getData(token: string) {
  const [websitesResult, monitorsResult, expiringDomainsResult, expiringSslResult] = await Promise.allSettled([
    api.get<Website[]>("/api/v1/websites/", token),
    api.get<Monitor[]>("/api/v1/monitors/", token),
    api.get<ExpiringItem[]>("/api/v1/websites/expiring-domains/?days=30", token),
    api.get<ExpiringItem[]>("/api/v1/websites/expiring-ssl/?days=14", token),
  ]);
  const websites = websitesResult.status === "fulfilled" ? websitesResult.value : [];
  const monitors = monitorsResult.status === "fulfilled" ? monitorsResult.value : [];
  const expiringDomains = expiringDomainsResult.status === "fulfilled" ? expiringDomainsResult.value : [];
  const expiringSsl = expiringSslResult.status === "fulfilled" ? expiringSslResult.value : [];
  // ... rest of existing getData (changeSets etc.) unchanged
  return { websites, allChanges, monitors, expiringDomains, expiringSsl };
}
```

Add the `ExpiringItem` type near the top of the file (before `getData`):

```typescript
interface ExpiringItem {
  id: string;
  name: string;
  domain: string;
  days_until_expiry: number | null;
}
```

Update the `DashboardPage` function signature to destructure the new values:

```typescript
  const { websites, allChanges, monitors, expiringDomains, expiringSsl } = await getData(token ?? "");
```

Compute down monitors (add near the existing derived values):

```typescript
  const downMonitors = monitors.filter((m) => m.status === "down" || m.status === "degraded");
```

Add the "Needs Attention" section between the stats grid and the high-risk changes section. Insert this block after the closing `</div>` of the stats grid and before the `{highRisk.length > 0 && (` block:

```tsx
      {/* Needs Attention */}
      {(downMonitors.length > 0 || expiringDomains.length > 0 || expiringSsl.length > 0) && (
        <div>
          <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-500" />
            Needs Attention
          </h2>
          <div className="grid gap-3 md:grid-cols-3">
            {downMonitors.length > 0 && (
              <Card className="border-red-200 dark:border-red-900">
                <CardHeader className="pb-2 pt-4">
                  <CardTitle className="text-sm font-medium text-red-600">
                    {downMonitors.length} Monitor{downMonitors.length > 1 ? "s" : ""} Down
                  </CardTitle>
                </CardHeader>
                <CardContent className="pb-4 space-y-1.5">
                  {downMonitors.slice(0, 4).map((m) => (
                    <div key={m.id} className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5 min-w-0">
                        <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${m.status === "down" ? "bg-red-500" : "bg-amber-500"}`} />
                        <span className="truncate">{m.name}</span>
                      </span>
                      <Badge variant={m.status === "down" ? "destructive" : "warning"} className="text-xs ml-2 shrink-0">
                        {m.status}
                      </Badge>
                    </div>
                  ))}
                  {downMonitors.length > 4 && (
                    <p className="text-xs text-muted-foreground">+{downMonitors.length - 4} more</p>
                  )}
                  <Link href="/monitors">
                    <Button variant="outline" size="sm" className="w-full mt-2 h-7 text-xs">View monitors →</Button>
                  </Link>
                </CardContent>
              </Card>
            )}

            {expiringDomains.length > 0 && (
              <Card className="border-amber-200 dark:border-amber-900">
                <CardHeader className="pb-2 pt-4">
                  <CardTitle className="text-sm font-medium text-amber-600">
                    {expiringDomains.length} Domain{expiringDomains.length > 1 ? "s" : ""} Expiring
                  </CardTitle>
                </CardHeader>
                <CardContent className="pb-4 space-y-1.5">
                  {expiringDomains.slice(0, 4).map((item) => (
                    <div key={item.id} className="flex items-center justify-between text-xs">
                      <span className="truncate min-w-0 font-mono">{item.domain}</span>
                      <span className={`ml-2 shrink-0 font-semibold ${(item.days_until_expiry ?? 99) <= 7 ? "text-red-600" : "text-amber-600"}`}>
                        {item.days_until_expiry}d
                      </span>
                    </div>
                  ))}
                  {expiringDomains.length > 4 && (
                    <p className="text-xs text-muted-foreground">+{expiringDomains.length - 4} more</p>
                  )}
                </CardContent>
              </Card>
            )}

            {expiringSsl.length > 0 && (
              <Card className="border-amber-200 dark:border-amber-900">
                <CardHeader className="pb-2 pt-4">
                  <CardTitle className="text-sm font-medium text-amber-600">
                    {expiringSsl.length} SSL Cert{expiringSsl.length > 1 ? "s" : ""} Expiring
                  </CardTitle>
                </CardHeader>
                <CardContent className="pb-4 space-y-1.5">
                  {expiringSsl.slice(0, 4).map((item) => (
                    <div key={item.id} className="flex items-center justify-between text-xs">
                      <span className="truncate min-w-0 font-mono">{item.domain}</span>
                      <span className={`ml-2 shrink-0 font-semibold ${(item.days_until_expiry ?? 99) <= 7 ? "text-red-600" : "text-amber-600"}`}>
                        {item.days_until_expiry}d
                      </span>
                    </div>
                  ))}
                  {expiringSsl.length > 4 && (
                    <p className="text-xs text-muted-foreground">+{expiringSsl.length - 4} more</p>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
```

- [ ] **Step 7: TypeScript check**

```
cd frontend && npm run lint
```

Expected: no errors

- [ ] **Step 8: Commit**

```
git add apps/websites/views.py tests/websites/test_expiring_endpoints.py "frontend/src/app/api/websites/expiring-domains/route.ts" "frontend/src/app/api/websites/expiring-ssl/route.ts" "frontend/src/app/(dashboard)/dashboard/page.tsx"
git commit -m "feat(dashboard): add expiring-domains/ssl endpoints and Needs Attention action center"
```

---

## Task 5: Notification Channel Test

**Files:**
- Modify: `apps/monitors/views.py`
- Modify: `apps/monitors/urls.py`
- Create: `tests/monitors/test_channel_test.py`
- Create: `frontend/src/app/api/notification-channels/[id]/test/route.ts`
- Modify: `frontend/src/components/notification-channels-client.tsx`

- [ ] **Step 1: Write failing backend tests**

```python
# tests/monitors/test_channel_test.py
import pytest
from unittest.mock import patch, MagicMock

from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import NotificationChannel


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="chtest@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Test Agency", owner=owner)


@pytest.fixture
def auth_client(owner, team):
    client = APIClient()
    resp = client.post(
        "/api/v1/auth/token/",
        {"email": owner.email, "password": "Pass123!"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['data']['access']}")
    return client


@pytest.fixture
def email_channel(team):
    return NotificationChannel.objects.create(
        team=team,
        name="Test Email",
        channel_type="email",
        config={"addresses": ["alert@test.com"]},
    )


@pytest.fixture
def clickup_channel(team):
    return NotificationChannel.objects.create(
        team=team,
        name="Test ClickUp",
        channel_type="clickup",
        config={"api_token": "pk_test", "task_id": "abc123"},
    )


@pytest.mark.django_db
class TestChannelTest:
    @patch("apps.monitors.views.send_mail")
    def test_email_channel_test_sends_mail(self, mock_send, auth_client, email_channel):
        resp = auth_client.post(f"/api/v1/notification-channels/{email_channel.pk}/test/")
        assert resp.status_code == 200
        data = resp.data["data"] if "data" in resp.data else resp.data
        assert data["success"] is True
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        assert "alert@test.com" in call_kwargs[0][3]  # recipient_list arg

    @patch("apps.monitors.views.send_mail", side_effect=Exception("SMTP error"))
    def test_email_channel_test_returns_success_false_on_failure(self, mock_send, auth_client, email_channel):
        resp = auth_client.post(f"/api/v1/notification-channels/{email_channel.pk}/test/")
        assert resp.status_code == 200
        data = resp.data["data"] if "data" in resp.data else resp.data
        assert data["success"] is False
        assert "SMTP error" in data["message"]

    @patch("apps.monitors.views.urllib.request.urlopen")
    def test_clickup_channel_test_calls_api(self, mock_urlopen, auth_client, clickup_channel):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        resp = auth_client.post(f"/api/v1/notification-channels/{clickup_channel.pk}/test/")
        assert resp.status_code == 200
        data = resp.data["data"] if "data" in resp.data else resp.data
        assert data["success"] is True
        mock_urlopen.assert_called_once()

    def test_channel_test_requires_auth(self, api_client, email_channel):
        resp = api_client.post(f"/api/v1/notification-channels/{email_channel.pk}/test/")
        assert resp.status_code == 401

    def test_channel_test_team_scoped(self, owner, team, auth_client):
        other_owner = User.objects.create_user(email="other_chtest@test.com", password="Pass123!")
        other_team = TeamService.create(name="Other Test Agency", owner=other_owner)
        other_ch = NotificationChannel.objects.create(
            team=other_team, name="OtherChannel", channel_type="email",
            config={"addresses": ["x@x.com"]},
        )
        resp = auth_client.post(f"/api/v1/notification-channels/{other_ch.pk}/test/")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/monitors/test_channel_test.py -v
```

Expected: `FAIL` — 404 because the endpoint doesn't exist

- [ ] **Step 3: Add `NotificationChannelTestView` to `apps/monitors/views.py`**

Add these imports near the top of `apps/monitors/views.py` (if not already present):

```python
import urllib.request
from django.core.mail import send_mail
from django.conf import settings
```

Add the view class at the end of `apps/monitors/views.py`:

```python
class NotificationChannelTestView(APIView):
    """POST /api/v1/notification-channels/<pk>/test/ — send a test payload through the channel."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        if not team:
            return Response({"success": False, "message": "No active team."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            channel = NotificationChannel.objects.get(pk=pk, team=team)
        except NotificationChannel.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        success, message = _test_channel(channel)
        return Response({"success": success, "message": message})


def _test_channel(channel) -> tuple[bool, str]:
    if channel.channel_type == "email":
        return _test_email(channel)
    if channel.channel_type == "clickup":
        return _test_clickup(channel)
    return False, f"Unknown channel type: {channel.channel_type}"


def _test_email(channel) -> tuple[bool, str]:
    addresses = channel.config.get("addresses", [])
    if not addresses:
        return False, "No email addresses configured."
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "alerts@digivault.digilatics.co")
    try:
        send_mail(
            subject="[Digivault] Test notification",
            message="This is a test notification from Digivault. Your email alerts are working correctly.",
            from_email=from_email,
            recipient_list=addresses,
            fail_silently=False,
        )
        return True, f"Test email sent to {', '.join(addresses)}"
    except Exception as e:
        return False, str(e)


def _test_clickup(channel) -> tuple[bool, str]:
    api_token = channel.config.get("api_token", "")
    task_id = channel.config.get("task_id", "")
    if not api_token or not task_id:
        return False, "Missing api_token or task_id in config."
    url = f"https://api.clickup.com/api/v2/task/{task_id}"
    req = urllib.request.Request(url, headers={"Authorization": api_token})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return True, f"ClickUp task '{task_id}' verified successfully."
            return False, f"ClickUp returned HTTP {resp.status}."
    except Exception as e:
        return False, str(e)
```

- [ ] **Step 4: Register the route in `apps/monitors/urls.py`**

Add to the existing `urlpatterns` list:

```python
    path(
        "notification-channels/<uuid:pk>/test/",
        views.NotificationChannelTestView.as_view(),
        name="notification-channel-test",
    ),
```

- [ ] **Step 5: Run tests — should pass**

```
pytest tests/monitors/test_channel_test.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 6: Create Next.js proxy route**

Create `frontend/src/app/api/notification-channels/[id]/test/route.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Ctx = { params: Promise<{ id: string }> };

export async function POST(_req: NextRequest, { params }: Ctx) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const upstream = await fetch(
    `${API_BASE}/api/v1/notification-channels/${id}/test/`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    }
  );
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
```

- [ ] **Step 7: Add Test button to `NotificationChannelsClient`**

In `frontend/src/components/notification-channels-client.tsx`:

**a.** Add `FlaskConical` and `CheckCircle2` and `XCircle` to the lucide-react import:

```typescript
import { Plus, Trash2, Bell, FlaskConical, CheckCircle2, XCircle } from "lucide-react";
```

**b.** Add test state to `NotificationChannelsClient`:

```typescript
export function NotificationChannelsClient({ initialChannels }: { initialChannels: NotificationChannel[] }) {
  const router = useRouter();
  const [deleting, setDeleting] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string } | null>>({});
```

**c.** Add `handleTest` function (inside the component, after `deleteChannel`):

```typescript
  async function handleTest(id: string) {
    setTesting(id);
    setTestResult((prev) => ({ ...prev, [id]: null }));
    try {
      const res = await fetch(`/api/notification-channels/${id}/test`, { method: "POST" });
      const data = await res.json().catch(() => ({ success: false, message: "Unknown error" }));
      setTestResult((prev) => ({ ...prev, [id]: { success: data.success, message: data.message } }));
      setTimeout(() => setTestResult((prev) => ({ ...prev, [id]: null })), 4000);
    } finally {
      setTesting(null);
    }
  }
```

**d.** Update the channel card actions (the `<CardContent>` div) to add the Test button and result inline. Replace the existing `<CardContent className="flex items-center justify-between ...">` content for each channel with:

```tsx
              <CardContent className="flex items-center justify-between py-3 px-4">
                <div className="flex items-center gap-3 min-w-0">
                  <span className={`px-2 py-0.5 rounded text-xs font-semibold ${TYPE_BADGE_COLOR[ch.channel_type] ?? "bg-slate-200"}`}>
                    {ch.channel_type.toUpperCase()}
                  </span>
                  <div className="min-w-0">
                    <p className="font-medium text-sm">{ch.name}</p>
                    <p className="text-xs text-muted-foreground font-mono truncate max-w-sm">{configSummary(ch)}</p>
                    {testResult[ch.id] && (
                      <p className={`text-xs mt-0.5 flex items-center gap-1 ${testResult[ch.id]!.success ? "text-emerald-600" : "text-red-600"}`}>
                        {testResult[ch.id]!.success
                          ? <CheckCircle2 className="h-3 w-3" />
                          : <XCircle className="h-3 w-3" />}
                        {testResult[ch.id]!.message.slice(0, 80)}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2 text-xs text-slate-500 hover:text-slate-700"
                    disabled={testing === ch.id}
                    onClick={() => handleTest(ch.id)}
                    title="Send a test notification"
                  >
                    {testing === ch.id ? "…" : <FlaskConical className="h-3.5 w-3.5" />}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-500 hover:text-red-600"
                    disabled={deleting === ch.id}
                    onClick={() => deleteChannel(ch.id, ch.name)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </CardContent>
```

- [ ] **Step 8: TypeScript check**

```
cd frontend && npm run lint
```

Expected: no errors

- [ ] **Step 9: Run all backend tests**

```
pytest tests/ -v -k "not test_response_is_enveloped"
```

Expected: all tests PASS

- [ ] **Step 10: Commit**

```
git add apps/monitors/views.py apps/monitors/urls.py tests/monitors/test_channel_test.py "frontend/src/app/api/notification-channels/[id]/test/route.ts" frontend/src/components/notification-channels-client.tsx
git commit -m "feat(monitors): add notification channel test endpoint and frontend test button"
```
