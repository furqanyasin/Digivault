# Credential Team Sharing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-credential sharing so owners/managers see everything, while developers see only credentials they created or had explicitly shared with them via a new Share dialog.

**Architecture:** New `CredentialShare` join table + `Credential.objects.visible_to(user)` queryset filter replaces the team-level filter on every credential endpoint. A `can_modify_credential` helper guards write endpoints. New `/credentials/<pk>/shares/` endpoints manage share rows. Frontend splits the existing misnamed "Share" dialog into a true read-only Reveal dialog plus a new Share-with-team dialog. A data migration backfills shares for current developers to preserve existing access.

**Tech Stack:** Django 5.1 + DRF + PostgreSQL (backend), Next.js 16 + React 19 + Tailwind v4 + react-query (frontend), pytest with `--reuse-db`.

**Spec:** [docs/superpowers/specs/2026-05-26-credential-team-sharing-design.md](../specs/2026-05-26-credential-team-sharing-design.md)

---

## File map

**Create:**
- `apps/credentials/permissions.py` — `can_modify_credential(user, credential)` and `can_view_credential(user, credential)` helpers.
- `apps/credentials/migrations/0005_credentialshare_and_backfill.py` — schema + data migration.
- `tests/credentials/test_sharing.py` — sharing tests.
- `tests/credentials/test_visibility.py` — visibility / queryset tests.
- `frontend/src/components/credential-share-dialog.tsx` — new dialog.

**Modify:**
- `apps/credentials/models.py` — add `CredentialShare`, `CredentialQuerySet.visible_to`, `Credential.objects = CredentialQuerySet.as_manager()`.
- `apps/credentials/serializers.py` — `CredentialShareSerializer`, `CredentialShareWriteSerializer`, expose `created_by_id` on `CredentialSerializer`.
- `apps/credentials/views.py` — swap querysets to `visible_to`, gate modify endpoints, add share views.
- `apps/credentials/urls.py` — wire share routes.
- `apps/audit/models.py` — add `CREDENTIAL_SHARED`, `CREDENTIAL_UNSHARED` actions.
- `frontend/src/lib/api.ts` — add `created_by_id` on `Credential`, add `CredentialShare` type.
- `frontend/src/app/(dashboard)/credentials/page.tsx` — pass `members` to client.
- `frontend/src/components/credentials-vault-client.tsx` — rename Share→Reveal on the existing dialog, add Share icon + dialog wiring, tighten edit/delete visibility to `can_modify`.

---

## Task 1: Add audit actions

**Files:**
- Modify: `apps/audit/models.py`

- [ ] **Step 1: Add the two new action choices**

In [apps/audit/models.py](apps/audit/models.py), inside `ActivityLog.Action`, after `CREDENTIAL_DELETED`:

```python
        CREDENTIAL_SHARED = "credential.shared", "Credential shared"
        CREDENTIAL_UNSHARED = "credential.unshared", "Credential unshared"
```

- [ ] **Step 2: Commit**

```bash
git add apps/audit/models.py
git commit -m "feat(audit): add CREDENTIAL_SHARED/UNSHARED actions"
```

---

## Task 2: Add CredentialShare model + visibility queryset

**Files:**
- Modify: `apps/credentials/models.py`

- [ ] **Step 1: Add imports and queryset class at the top of models.py**

After the existing imports in [apps/credentials/models.py](apps/credentials/models.py), add:

```python
from django.db.models import Q
```

Above the `Credential` class:

```python
class CredentialQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Filter to credentials the given user may see.

        Visibility rules:
        - Owners and managers of the credential's team see everything.
        - The user who created the credential always sees it.
        - Any user with a CredentialShare row sees it.
        """
        if user is None or not user.is_authenticated:
            return self.none()

        from apps.accounts.models import TeamMembership

        privileged_team_ids = TeamMembership.objects.filter(
            user=user,
            role__in=[TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER],
        ).values_list("team_id", flat=True)

        return self.filter(
            Q(team_id__in=privileged_team_ids)
            | Q(created_by=user)
            | Q(shares__user=user)
        ).distinct()
```

- [ ] **Step 2: Attach the manager and add CredentialShare model**

Modify the `Credential` class to use the queryset as its manager. Inside `class Credential(BaseModel):`, add right after the `class Meta` block (or before it — order doesn't matter, but keep it inside the class):

```python
    objects = CredentialQuerySet.as_manager()
```

At the bottom of the file (after `CredentialAccessLog`), add:

```python
class CredentialShare(BaseModel):
    """Grants a developer view+reveal access to a single credential.

    Owners and managers do not need rows here — their access is implicit
    via role.  A creator also does not need a row.  Modification of the
    credential remains gated by `can_modify_credential`.
    """

    credential = models.ForeignKey(
        Credential, on_delete=models.CASCADE, related_name="shares"
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="credential_shares",
    )
    shared_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credential_shares_granted",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["credential", "user"],
                name="credentialshare_unique_per_user",
            )
        ]
        indexes = [models.Index(fields=["user", "credential"])]

    def __str__(self) -> str:
        return f"{self.credential.label} → {self.user.email}"
```

- [ ] **Step 3: Generate the schema migration**

Run: `python manage.py makemigrations credentials`
Expected: a new file `apps/credentials/migrations/0005_credentialshare.py` is created.

- [ ] **Step 4: Rename the migration so it can hold the data backfill**

Rename `apps/credentials/migrations/0005_credentialshare.py` → `apps/credentials/migrations/0005_credentialshare_and_backfill.py`. Verify the file's `dependencies = [("credentials", "0004_credential_team_nullable_website")]`.

- [ ] **Step 5: Add the data backfill operation**

Open the renamed migration. After the `migrations.CreateModel(...)` operation in `operations = [...]`, append a `RunPython` op:

```python
def backfill_developer_shares(apps, schema_editor):
    Credential = apps.get_model("credentials", "Credential")
    CredentialShare = apps.get_model("credentials", "CredentialShare")
    TeamMembership = apps.get_model("accounts", "TeamMembership")

    to_create = []
    for cred in Credential.objects.all().only("id", "team_id", "created_by_id"):
        dev_user_ids = TeamMembership.objects.filter(
            team_id=cred.team_id, role="developer",
        ).values_list("user_id", flat=True)
        for uid in dev_user_ids:
            if uid == cred.created_by_id:
                continue
            to_create.append(CredentialShare(
                credential_id=cred.id, user_id=uid, shared_by=None,
            ))
    if to_create:
        CredentialShare.objects.bulk_create(to_create, ignore_conflicts=True)


def noop_reverse(apps, schema_editor):
    apps.get_model("credentials", "CredentialShare").objects.all().delete()
```

Then add to `operations`:

```python
        migrations.RunPython(backfill_developer_shares, noop_reverse),
```

(Put the two function `def`s above the `class Migration` block in the same file.)

- [ ] **Step 6: Apply the migration**

Run: `python manage.py migrate credentials`
Expected: `Applying credentials.0005_credentialshare_and_backfill... OK`.

- [ ] **Step 7: Commit**

```bash
git add apps/credentials/models.py apps/credentials/migrations/0005_credentialshare_and_backfill.py
git commit -m "feat(credentials): add CredentialShare model + visible_to queryset"
```

---

## Task 3: Test the visibility queryset

**Files:**
- Create: `tests/credentials/test_visibility.py`

- [ ] **Step 1: Write the failing tests**

Create [tests/credentials/test_visibility.py](tests/credentials/test_visibility.py):

```python
import pytest

from apps.accounts.models import TeamMembership
from apps.credentials.models import Credential, CredentialShare
from apps.credentials.services import CredentialService


@pytest.fixture
def team(db, django_user_model):
    from apps.accounts.models import Team
    return Team.objects.create(name="Acme", slug="acme")


@pytest.fixture
def make_user(db, django_user_model):
    def _make(email, team, role):
        u = django_user_model.objects.create_user(email=email, password="x")
        TeamMembership.objects.create(user=u, team=team, role=role)
        u.active_team = team
        u.save(update_fields=["active_team"])
        return u
    return _make


@pytest.fixture
def cred(team, make_user):
    creator = make_user("creator@x.io", team, TeamMembership.Role.DEVELOPER)
    return CredentialService.create(
        team=team, website=None, label="DB",
        credential_type="custom", login_url="",
        username="u", password="p", notes="",
        created_by=creator,
    )


def test_owner_sees_all(team, make_user, cred):
    owner = make_user("owner@x.io", team, TeamMembership.Role.OWNER)
    assert Credential.objects.visible_to(owner).filter(pk=cred.pk).exists()


def test_manager_sees_all(team, make_user, cred):
    mgr = make_user("mgr@x.io", team, TeamMembership.Role.MANAGER)
    assert Credential.objects.visible_to(mgr).filter(pk=cred.pk).exists()


def test_creator_sees_own(cred):
    creator = cred.created_by
    assert Credential.objects.visible_to(creator).filter(pk=cred.pk).exists()


def test_unrelated_developer_does_not_see(team, make_user, cred):
    dev = make_user("dev@x.io", team, TeamMembership.Role.DEVELOPER)
    assert not Credential.objects.visible_to(dev).filter(pk=cred.pk).exists()


def test_shared_developer_sees(team, make_user, cred):
    dev = make_user("dev@x.io", team, TeamMembership.Role.DEVELOPER)
    CredentialShare.objects.create(credential=cred, user=dev)
    assert Credential.objects.visible_to(dev).filter(pk=cred.pk).exists()


def test_anon_sees_nothing(cred, django_user_model):
    from django.contrib.auth.models import AnonymousUser
    assert not Credential.objects.visible_to(AnonymousUser()).exists()
```

- [ ] **Step 2: Run and confirm pass**

Run: `pytest tests/credentials/test_visibility.py -v`
Expected: all 6 tests pass. If any fail because of fixture detail mismatches (e.g. team creation), inspect and fix only fixture wiring — do not relax assertions.

- [ ] **Step 3: Commit**

```bash
git add tests/credentials/test_visibility.py
git commit -m "test(credentials): cover visible_to queryset"
```

---

## Task 4: Add permission helpers

**Files:**
- Create: `apps/credentials/permissions.py`

- [ ] **Step 1: Write the helpers**

Create [apps/credentials/permissions.py](apps/credentials/permissions.py):

```python
from apps.accounts.models import TeamMembership


def _user_role(user, team) -> str | None:
    if user is None or not user.is_authenticated or team is None:
        return None
    membership = TeamMembership.objects.filter(user=user, team=team).first()
    return membership.role if membership else None


def can_view_credential(user, credential) -> bool:
    role = _user_role(user, credential.team)
    if role in (TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER):
        return True
    if credential.created_by_id == getattr(user, "id", None):
        return True
    return credential.shares.filter(user=user).exists()


def can_modify_credential(user, credential) -> bool:
    """Edit / delete / share / unshare permission.

    Allowed when the user is an owner or manager of the credential's
    team, or is the credential's creator.  A shared developer cannot
    modify.
    """
    role = _user_role(user, credential.team)
    if role in (TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER):
        return True
    return credential.created_by_id == getattr(user, "id", None)
```

- [ ] **Step 2: Commit**

```bash
git add apps/credentials/permissions.py
git commit -m "feat(credentials): add can_view/can_modify helpers"
```

---

## Task 5: Switch endpoints to visibility filter + modify guards

**Files:**
- Modify: `apps/credentials/views.py`

- [ ] **Step 1: Add the import**

In [apps/credentials/views.py](apps/credentials/views.py), with the other imports:

```python
from apps.credentials.permissions import can_modify_credential
```

- [ ] **Step 2: Replace the four querysets**

In `TeamCredentialListCreateView.get_queryset` ([apps/credentials/views.py:55-59](apps/credentials/views.py#L55-L59)), replace the body with:

```python
        team = self.request.user.active_team
        if team is None:
            return Credential.objects.none()
        return (
            Credential.objects.visible_to(self.request.user)
            .filter(team=team)
            .select_related("website")
        )
```

In `CredentialListCreateView.get_queryset` ([apps/credentials/views.py:114-121](apps/credentials/views.py#L114-L121)):

```python
        team = self.request.user.active_team
        if team is None:
            return Credential.objects.none()
        return (
            Credential.objects.visible_to(self.request.user)
            .filter(team=team, website_id=self.kwargs["website_pk"])
            .select_related("website")
        )
```

In `CredentialDetailView.get_queryset` ([apps/credentials/views.py:167-171](apps/credentials/views.py#L167-L171)):

```python
        team = self.request.user.active_team
        if team is None:
            return Credential.objects.none()
        return (
            Credential.objects.visible_to(self.request.user)
            .filter(team=team)
            .select_related("website")
        )
```

In `CredentialRevealView.post` ([apps/credentials/views.py:215-220](apps/credentials/views.py#L215-L220)), replace the lookup line:

```python
        try:
            credential = (
                Credential.objects.visible_to(request.user)
                .get(pk=pk, team=team)
            )
        except Credential.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
```

In `ExtensionCredentialLookupView.get_queryset` ([apps/credentials/views.py:272-280](apps/credentials/views.py#L272-L280)):

```python
        team = self.request.user.active_team
        if team is None:
            return Credential.objects.none()
        domain = self.request.query_params.get("domain", "").strip().lower()
        return Credential.objects.visible_to(self.request.user).filter(
            website__team=team,
            website__domain__iexact=domain,
        )
```

- [ ] **Step 3: Gate update/delete with can_modify**

In `CredentialDetailView.update` ([apps/credentials/views.py:173](apps/credentials/views.py#L173)), at the top of the method right after `credential = self.get_object()`, add:

```python
        if not can_modify_credential(request.user, credential):
            return Response(status=status.HTTP_403_FORBIDDEN)
```

In `CredentialDetailView.perform_destroy` ([apps/credentials/views.py:197-203](apps/credentials/views.py#L197-L203)):

```python
    def perform_destroy(self, instance):
        if not can_modify_credential(self.request.user, instance):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        AuditService.log_request(
            self.request, ActivityLog.Action.CREDENTIAL_DELETED,
            description=f"Deleted credential '{instance.label}'",
            resource_type="credential", resource_id=instance.pk,
        )
        instance.delete()
```

- [ ] **Step 4: Run existing credential tests to confirm no regression**

Run: `pytest tests/credentials -v`
Expected: all tests pass. If any fail, inspect — they may be testing the old behaviour where any team member could read everything. If so, update the test to align with the new rule (owner role on the test user, or add a CredentialShare row).

- [ ] **Step 5: Commit**

```bash
git add apps/credentials/views.py
git commit -m "feat(credentials): filter all reads by visible_to; gate writes"
```

---

## Task 6: Share serializers

**Files:**
- Modify: `apps/credentials/serializers.py`

- [ ] **Step 1: Expose created_by_id on CredentialSerializer**

Modify the `CredentialSerializer` class in [apps/credentials/serializers.py](apps/credentials/serializers.py) — add `"created_by_id"` to its `Meta.fields` and `Meta.read_only_fields`:

```python
    class Meta:
        model = Credential
        fields = (
            "id",
            "website_id",
            "website_name",
            "label",
            "credential_type",
            "login_url",
            "created_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id", "website_id", "website_name", "created_by_id",
            "created_at", "updated_at",
        )
```

- [ ] **Step 2: Add share serializers at the bottom of the file**

```python
from apps.credentials.models import CredentialShare  # add to imports at top


class CredentialShareSerializer(BaseModelSerializer):
    user_id = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    shared_by_email = serializers.SerializerMethodField()

    class Meta:
        model = CredentialShare
        fields = ("id", "user_id", "email", "name", "role",
                  "shared_by_email", "created_at")
        read_only_fields = fields

    def get_user_id(self, obj) -> str:
        return str(obj.user_id)

    def get_email(self, obj) -> str:
        return obj.user.email

    def get_name(self, obj) -> str:
        first = obj.user.first_name or ""
        last = obj.user.last_name or ""
        return (first + " " + last).strip() or obj.user.email

    def get_role(self, obj) -> str:
        from apps.accounts.models import TeamMembership
        m = TeamMembership.objects.filter(
            user=obj.user, team=obj.credential.team
        ).first()
        return m.role if m else "developer"

    def get_shared_by_email(self, obj) -> str | None:
        return obj.shared_by.email if obj.shared_by else None


class CredentialShareWriteSerializer(serializers.Serializer):
    user_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False
    )
```

- [ ] **Step 3: Commit**

```bash
git add apps/credentials/serializers.py
git commit -m "feat(credentials): add share serializers + created_by_id"
```

---

## Task 7: Share endpoints

**Files:**
- Modify: `apps/credentials/views.py`
- Modify: `apps/credentials/urls.py`

- [ ] **Step 1: Add the view classes to views.py**

Append to [apps/credentials/views.py](apps/credentials/views.py):

```python
from apps.credentials.models import CredentialShare
from apps.credentials.serializers import (
    CredentialShareSerializer,
    CredentialShareWriteSerializer,
)


class CredentialShareListCreateView(APIView):
    """GET/POST /api/v1/credentials/<pk>/shares/"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _get_credential(self, request, pk):
        team = request.user.active_team
        if team is None:
            return None
        return (
            Credential.objects
            .visible_to(request.user)
            .filter(pk=pk, team=team)
            .first()
        )

    def get(self, request, pk):
        cred = self._get_credential(request, pk)
        if cred is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        shares = cred.shares.select_related("user", "shared_by")
        return Response(
            CredentialShareSerializer(shares, many=True).data
        )

    def post(self, request, pk):
        cred = self._get_credential(request, pk)
        if cred is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not can_modify_credential(request.user, cred):
            return Response(status=status.HTTP_403_FORBIDDEN)

        ser = CredentialShareWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from apps.accounts.models import TeamMembership

        memberships = TeamMembership.objects.filter(
            team=cred.team, user_id__in=ser.validated_data["user_ids"]
        ).select_related("user")
        valid_user_ids = {m.user_id for m in memberships}
        invalid = set(ser.validated_data["user_ids"]) - valid_user_ids
        if invalid:
            return Response(
                {"detail": f"Users not in team: {sorted(str(u) for u in invalid)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Only developers need shares; owners/managers already have access.
        target_user_ids = [
            m.user_id for m in memberships
            if m.role == TeamMembership.Role.DEVELOPER
        ]
        created_ids = []
        for uid in target_user_ids:
            _, created = CredentialShare.objects.get_or_create(
                credential=cred, user_id=uid,
                defaults={"shared_by": request.user},
            )
            if created:
                created_ids.append(str(uid))

        if created_ids:
            AuditService.log_request(
                request, ActivityLog.Action.CREDENTIAL_SHARED,
                description=f"Shared credential '{cred.label}' with {len(created_ids)} user(s)",
                resource_type="credential", resource_id=cred.pk,
                metadata={"shared_with_user_ids": created_ids},
            )

        shares = cred.shares.select_related("user", "shared_by")
        return Response(
            CredentialShareSerializer(shares, many=True).data,
            status=status.HTTP_201_CREATED if created_ids else status.HTTP_200_OK,
        )


class CredentialShareDeleteView(APIView):
    """DELETE /api/v1/credentials/<pk>/shares/<user_id>/"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def delete(self, request, pk, user_id):
        team = request.user.active_team
        if team is None:
            return Response(status=status.HTTP_403_FORBIDDEN)
        try:
            cred = Credential.objects.get(pk=pk, team=team)
        except Credential.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not can_modify_credential(request.user, cred):
            return Response(status=status.HTTP_403_FORBIDDEN)
        deleted, _ = CredentialShare.objects.filter(
            credential=cred, user_id=user_id
        ).delete()
        if not deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)

        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_UNSHARED,
            description=f"Unshared credential '{cred.label}'",
            resource_type="credential", resource_id=cred.pk,
            metadata={"unshared_user_id": str(user_id)},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 2: Wire the URLs**

Update [apps/credentials/urls.py](apps/credentials/urls.py):

```python
from apps.credentials.views import (
    CredentialAccessLogView,
    CredentialDetailView,
    CredentialListCreateView,
    CredentialRevealView,
    CredentialShareDeleteView,
    CredentialShareListCreateView,
    TeamCredentialListCreateView,
)

urlpatterns = [
    # ...existing entries unchanged...
    path(
        "credentials/<uuid:pk>/shares/",
        CredentialShareListCreateView.as_view(),
        name="credential-share-list-create",
    ),
    path(
        "credentials/<uuid:pk>/shares/<uuid:user_id>/",
        CredentialShareDeleteView.as_view(),
        name="credential-share-delete",
    ),
]
```

(Keep the existing five entries; insert the two new ones at the end of the list.)

- [ ] **Step 3: Commit**

```bash
git add apps/credentials/views.py apps/credentials/urls.py
git commit -m "feat(credentials): add share list/create/delete endpoints"
```

---

## Task 8: Test the share endpoints

**Files:**
- Create: `tests/credentials/test_sharing.py`

- [ ] **Step 1: Write the failing tests**

Create [tests/credentials/test_sharing.py](tests/credentials/test_sharing.py):

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Team, TeamMembership
from apps.audit.models import ActivityLog
from apps.credentials.models import Credential, CredentialShare
from apps.credentials.services import CredentialService


@pytest.fixture
def team(db):
    return Team.objects.create(name="Acme", slug="acme")


@pytest.fixture
def make_user(db, django_user_model):
    def _make(email, team, role):
        u = django_user_model.objects.create_user(email=email, password="x")
        TeamMembership.objects.create(user=u, team=team, role=role)
        u.active_team = team
        u.save(update_fields=["active_team"])
        return u
    return _make


@pytest.fixture
def owner(team, make_user):
    return make_user("owner@x.io", team, TeamMembership.Role.OWNER)


@pytest.fixture
def manager(team, make_user):
    return make_user("mgr@x.io", team, TeamMembership.Role.MANAGER)


@pytest.fixture
def dev1(team, make_user):
    return make_user("dev1@x.io", team, TeamMembership.Role.DEVELOPER)


@pytest.fixture
def dev2(team, make_user):
    return make_user("dev2@x.io", team, TeamMembership.Role.DEVELOPER)


@pytest.fixture
def cred(team, dev1):
    return CredentialService.create(
        team=team, website=None, label="DB",
        credential_type="custom", login_url="",
        username="u", password="p", notes="",
        created_by=dev1,
    )


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_owner_can_share(cred, owner, dev2):
    resp = _client(owner).post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(dev2.id)]}, format="json",
    )
    assert resp.status_code == 201
    assert CredentialShare.objects.filter(credential=cred, user=dev2).exists()
    assert ActivityLog.objects.filter(
        action=ActivityLog.Action.CREDENTIAL_SHARED
    ).exists()


def test_manager_can_share(cred, manager, dev2):
    resp = _client(manager).post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(dev2.id)]}, format="json",
    )
    assert resp.status_code == 201


def test_creator_can_share(cred, dev1, dev2):
    resp = _client(dev1).post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(dev2.id)]}, format="json",
    )
    assert resp.status_code == 201


def test_shared_dev_cannot_share(cred, dev1, dev2, make_user, team):
    dev3 = make_user("dev3@x.io", team, TeamMembership.Role.DEVELOPER)
    CredentialShare.objects.create(credential=cred, user=dev2)
    resp = _client(dev2).post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(dev3.id)]}, format="json",
    )
    assert resp.status_code == 403


def test_unrelated_dev_cannot_see(cred, dev2):
    resp = _client(dev2).get(f"/api/v1/credentials/{cred.pk}/")
    assert resp.status_code == 404


def test_shared_dev_can_view_and_reveal(cred, dev2):
    CredentialShare.objects.create(credential=cred, user=dev2)
    c = _client(dev2)
    assert c.get(f"/api/v1/credentials/{cred.pk}/").status_code == 200
    assert c.post(f"/api/v1/credentials/{cred.pk}/reveal/").status_code == 200


def test_shared_dev_cannot_edit_or_delete(cred, dev2):
    CredentialShare.objects.create(credential=cred, user=dev2)
    c = _client(dev2)
    assert c.patch(
        f"/api/v1/credentials/{cred.pk}/",
        {"label": "nope"}, format="json",
    ).status_code == 403
    assert c.delete(f"/api/v1/credentials/{cred.pk}/").status_code == 403


def test_share_with_manager_is_noop(cred, owner, manager):
    resp = _client(owner).post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(manager.id)]}, format="json",
    )
    assert resp.status_code == 200
    assert not CredentialShare.objects.filter(
        credential=cred, user=manager
    ).exists()


def test_share_with_non_team_member_is_400(cred, owner, db, django_user_model):
    outsider = django_user_model.objects.create_user(
        email="out@x.io", password="x"
    )
    resp = _client(owner).post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(outsider.id)]}, format="json",
    )
    assert resp.status_code == 400


def test_unshare_revokes_access(cred, owner, dev2):
    CredentialShare.objects.create(credential=cred, user=dev2)
    assert _client(dev2).get(
        f"/api/v1/credentials/{cred.pk}/"
    ).status_code == 200

    resp = _client(owner).delete(
        f"/api/v1/credentials/{cred.pk}/shares/{dev2.id}/"
    )
    assert resp.status_code == 204
    assert _client(dev2).get(
        f"/api/v1/credentials/{cred.pk}/"
    ).status_code == 404
    assert ActivityLog.objects.filter(
        action=ActivityLog.Action.CREDENTIAL_UNSHARED
    ).exists()


def test_share_list_returns_current_shares(cred, owner, dev2):
    CredentialShare.objects.create(
        credential=cred, user=dev2, shared_by=owner
    )
    resp = _client(owner).get(f"/api/v1/credentials/{cred.pk}/shares/")
    assert resp.status_code == 200
    body = resp.json()
    # Envelope wraps payload as data: [...]
    rows = body["data"] if isinstance(body, dict) and "data" in body else body
    assert len(rows) == 1
    assert rows[0]["email"] == "dev2@x.io"
    assert rows[0]["shared_by_email"] == "owner@x.io"
```

- [ ] **Step 2: Run and confirm pass**

Run: `pytest tests/credentials/test_sharing.py -v`
Expected: all 11 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/credentials/test_sharing.py
git commit -m "test(credentials): cover share endpoints + access rules"
```

---

## Task 9: Run full backend test suite

- [ ] **Step 1: Run all tests**

Run: `pytest`
Expected: all tests pass. If any pre-existing credential tests fail, they are likely asserting the old "any team member sees all" behaviour. Update them to either grant the test user owner role or add a `CredentialShare` row — do not relax the new security model.

- [ ] **Step 2: Commit any test fixes**

```bash
git add -p   # review each hunk
git commit -m "test(credentials): align legacy tests with new visibility model"
```

(Skip the commit if no test changes were required.)

---

## Task 10: Frontend types

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Extend the Credential type and add CredentialShare**

In [frontend/src/lib/api.ts](frontend/src/lib/api.ts), find the `Credential` interface (around line 157) and add `created_by_id`:

```ts
export interface Credential {
  id: string;
  website_id: string | null;
  website_name: string | null;
  credential_type: string;
  label: string;
  login_url: string;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
}
```

Then add, after `TeamMember`:

```ts
export interface CredentialShare {
  id: string;
  user_id: string;
  email: string;
  name: string;
  role: string;
  shared_by_email: string | null;
  created_at: string;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): types for credential shares"
```

---

## Task 11: Page passes members + me down

**Files:**
- Modify: `frontend/src/app/(dashboard)/credentials/page.tsx`

- [ ] **Step 1: Update the page to fetch + forward members**

Replace [frontend/src/app/(dashboard)/credentials/page.tsx](frontend/src/app/(dashboard)/credentials/page.tsx) with:

```tsx
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, Credential, User, TeamMember } from "@/lib/api";
import { CredentialsVaultClient } from "@/components/credentials-vault-client";

export default async function CredentialsPage() {
  const token = await getAccessToken();

  const [credentials, websites, me] = await Promise.all([
    api.get<Credential[]>("/api/v1/credentials/", token ?? "").catch(() => [] as Credential[]),
    api.get<Website[]>("/api/v1/websites/", token ?? "").catch(() => [] as Website[]),
    api.get<User>("/api/v1/auth/me/", token ?? "").catch(() => null as User | null),
  ]);

  let myRole = "developer";
  let members: TeamMember[] = [];
  if (me?.active_team) {
    members = await api
      .get<TeamMember[]>(`/api/v1/auth/teams/${me.active_team}/members/`, token ?? "")
      .catch(() => [] as TeamMember[]);
    const membership = members.find((m) => m.user.id === me.id);
    if (membership) myRole = membership.role;
  }

  return (
    <CredentialsVaultClient
      initialCredentials={credentials}
      websites={websites}
      myRole={myRole}
      myUserId={me?.id ?? null}
      members={members}
    />
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/(dashboard)/credentials/page.tsx
git commit -m "feat(frontend): pass members + me to credentials client"
```

---

## Task 12: Share dialog component

**Files:**
- Create: `frontend/src/components/credential-share-dialog.tsx`

- [ ] **Step 1: Build the component**

Create [frontend/src/components/credential-share-dialog.tsx](frontend/src/components/credential-share-dialog.tsx):

```tsx
"use client";

import { useState, useEffect, useMemo } from "react";
import { Share2, X, Loader2, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import type { CredentialShare, TeamMember } from "@/lib/api";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  credentialId: string;
  credentialLabel: string;
  members: TeamMember[];
}

export function CredentialShareDialog({
  open, onOpenChange, credentialId, credentialLabel, members,
}: Props) {
  const { toast } = useToast();
  const [shares, setShares] = useState<CredentialShare[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");

  const owners = useMemo(
    () => members.filter((m) => m.role === "owner" || m.role === "manager"),
    [members],
  );
  const developers = useMemo(
    () => members.filter((m) => m.role === "developer"),
    [members],
  );

  const sharedUserIds = useMemo(
    () => new Set(shares.map((s) => s.user_id)),
    [shares],
  );

  const addable = useMemo(
    () => developers.filter(
      (m) => !sharedUserIds.has(m.user.id) &&
        (search.trim() === "" ||
          m.user.email.toLowerCase().includes(search.toLowerCase()) ||
          `${m.user.first_name} ${m.user.last_name}`
            .toLowerCase()
            .includes(search.toLowerCase())),
    ),
    [developers, sharedUserIds, search],
  );

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setSelectedIds(new Set());
    setSearch("");
    fetch(`/api/credentials/${credentialId}/shares/`)
      .then((r) => r.json())
      .then((body) => {
        const rows = body?.data ?? body ?? [];
        setShares(Array.isArray(rows) ? rows : []);
      })
      .catch(() => toast({
        title: "Could not load shares",
        variant: "destructive",
      }))
      .finally(() => setLoading(false));
  }, [open, credentialId, toast]);

  function toggleSelected(userId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  async function handleShare() {
    if (selectedIds.size === 0) return;
    setLoading(true);
    try {
      const resp = await fetch(`/api/credentials/${credentialId}/shares/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_ids: Array.from(selectedIds) }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const body = await resp.json();
      const rows = body?.data ?? body ?? [];
      setShares(Array.isArray(rows) ? rows : []);
      setSelectedIds(new Set());
      toast({ title: "Shared" });
    } catch {
      toast({ title: "Share failed", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }

  async function handleRevoke(userId: string) {
    setBusyUserId(userId);
    try {
      const resp = await fetch(
        `/api/credentials/${credentialId}/shares/${userId}/`,
        { method: "DELETE" },
      );
      if (!resp.ok && resp.status !== 204) throw new Error();
      setShares((prev) => prev.filter((s) => s.user_id !== userId));
      toast({ title: "Access revoked" });
    } catch {
      toast({ title: "Could not revoke", variant: "destructive" });
    } finally {
      setBusyUserId(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Share2 className="h-4 w-4" />
            Share &ldquo;{credentialLabel}&rdquo;
          </DialogTitle>
          <p className="text-xs text-muted-foreground">
            Choose which team members can view and reveal this credential.
          </p>
        </DialogHeader>

        <div className="space-y-5 pt-2">
          <section>
            <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
              Always has access
            </p>
            <div className="flex flex-wrap gap-1.5">
              {owners.length === 0 && (
                <span className="text-xs text-muted-foreground">
                  No owners or managers in this team yet.
                </span>
              )}
              {owners.map((m) => (
                <span
                  key={m.user.id}
                  className="text-xs px-2 py-1 rounded-full bg-muted border"
                >
                  {m.user.first_name || m.user.email}{" "}
                  <span className="text-muted-foreground">({m.role})</span>
                </span>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground mt-1.5">
              Owners and managers automatically see all team credentials.
            </p>
          </section>

          <section>
            <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
              Shared with
            </p>
            {loading && shares.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> Loading…
              </div>
            ) : shares.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Not shared with any developer yet.
              </p>
            ) : (
              <ul className="space-y-1">
                {shares.map((s) => (
                  <li
                    key={s.id}
                    className="flex items-center justify-between text-sm rounded px-2 py-1.5 hover:bg-muted/50"
                  >
                    <div className="min-w-0">
                      <p className="truncate">{s.name}</p>
                      <p className="text-[11px] text-muted-foreground truncate">
                        {s.email}
                        {s.shared_by_email && ` · shared by ${s.shared_by_email}`}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 w-7 p-0"
                      disabled={busyUserId === s.user_id}
                      onClick={() => handleRevoke(s.user_id)}
                      aria-label="Revoke access"
                    >
                      {busyUserId === s.user_id
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        : <X className="h-3.5 w-3.5" />}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
              Add developers
            </p>
            <Input
              placeholder="Search by name or email"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="mb-2"
            />
            {addable.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No developers available to share with.
              </p>
            ) : (
              <ul className="space-y-1 max-h-48 overflow-y-auto border rounded">
                {addable.map((m) => {
                  const selected = selectedIds.has(m.user.id);
                  return (
                    <li key={m.user.id}>
                      <button
                        type="button"
                        onClick={() => toggleSelected(m.user.id)}
                        className={`w-full flex items-center justify-between px-2 py-1.5 text-left text-sm ${
                          selected ? "bg-muted" : "hover:bg-muted/50"
                        }`}
                      >
                        <span className="min-w-0">
                          <span className="block truncate">
                            {`${m.user.first_name} ${m.user.last_name}`.trim()
                              || m.user.email}
                          </span>
                          <span className="block text-[11px] text-muted-foreground truncate">
                            {m.user.email}
                          </span>
                        </span>
                        {selected && <Check className="h-4 w-4 shrink-0" />}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
            <div className="flex justify-end mt-3">
              <Button
                size="sm"
                onClick={handleShare}
                disabled={selectedIds.size === 0 || loading}
              >
                {loading
                  ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                  : <Share2 className="h-3.5 w-3.5 mr-1.5" />}
                Share with {selectedIds.size || "…"}
              </Button>
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/credential-share-dialog.tsx
git commit -m "feat(frontend): credential share dialog"
```

---

## Task 13: Frontend API route proxies for shares

**Files:**
- Create: `frontend/src/app/api/credentials/[id]/shares/route.ts`
- Create: `frontend/src/app/api/credentials/[id]/shares/[userId]/route.ts`

- [ ] **Step 1: Look at the existing reveal proxy for the pattern**

Run: open [frontend/src/app/api/credentials/[id]/reveal/route.ts](frontend/src/app/api/credentials/[id]/reveal/route.ts) and read it. Copy its structure (it forwards cookie auth and calls the Django backend). The same pattern applies here.

- [ ] **Step 2: Create the list/create proxy**

Create [frontend/src/app/api/credentials/[id]/shares/route.ts](frontend/src/app/api/credentials/[id]/shares/route.ts) following the same auth pattern as the reveal route:

```ts
import { NextRequest, NextResponse } from "next/server";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const token = await getAccessToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  try {
    const data = await api.get(`/api/v1/credentials/${id}/shares/`, token);
    return NextResponse.json(data);
  } catch (e: unknown) {
    const status = (e as { status?: number })?.status ?? 500;
    return NextResponse.json({ error: "failed" }, { status });
  }
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const token = await getAccessToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const body = await req.json();
  try {
    const data = await api.post(`/api/v1/credentials/${id}/shares/`, body, token);
    return NextResponse.json(data, { status: 201 });
  } catch (e: unknown) {
    const status = (e as { status?: number })?.status ?? 500;
    return NextResponse.json({ error: "failed" }, { status });
  }
}
```

If `api.get`/`api.post` envelope/return shapes differ in your codebase, match the exact pattern used by `route.ts` for reveal — do not introduce a new HTTP wrapper.

- [ ] **Step 3: Create the delete proxy**

Create [frontend/src/app/api/credentials/[id]/shares/[userId]/route.ts](frontend/src/app/api/credentials/[id]/shares/[userId]/route.ts):

```ts
import { NextRequest, NextResponse } from "next/server";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string; userId: string }> },
) {
  const { id, userId } = await params;
  const token = await getAccessToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  try {
    await api.delete(`/api/v1/credentials/${id}/shares/${userId}/`, token);
    return new NextResponse(null, { status: 204 });
  } catch (e: unknown) {
    const status = (e as { status?: number })?.status ?? 500;
    return NextResponse.json({ error: "failed" }, { status });
  }
}
```

If `api.delete` does not exist in `@/lib/api`, mirror the exact request shape used by other DELETE routes in this codebase (e.g. how the existing credential delete is proxied — search for `api.delete` first). Adjust this file to use the existing helper before continuing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/api/credentials/[id]/shares
git commit -m "feat(frontend): proxy routes for credential shares"
```

---

## Task 14: Wire dialog into credentials vault client

**Files:**
- Modify: `frontend/src/components/credentials-vault-client.tsx`

- [ ] **Step 1: Add props for the new data**

Find the existing top-level prop type for `CredentialsVaultClient`. Extend it:

```ts
interface CredentialsVaultClientProps {
  initialCredentials: Credential[];
  websites: Website[];
  myRole: string;
  myUserId: string | null;
  members: TeamMember[];
}
```

Update the function signature to destructure `myUserId` and `members`, and update the import:

```ts
import type { Credential, Website, TeamMember } from "@/lib/api";
import { CredentialShareDialog } from "@/components/credential-share-dialog";
```

- [ ] **Step 2: Define a canModify helper inside the component**

Near the top of the component body:

```ts
const canModify = (cred: Credential) => {
  if (myRole === "owner" || myRole === "manager") return true;
  return !!myUserId && cred.created_by_id === myUserId;
};
```

- [ ] **Step 3: Add share dialog state and handler**

In the same component body:

```ts
const [shareTarget, setShareTarget] = useState<Credential | null>(null);
```

- [ ] **Step 4: Replace the existing Share button on each card with a Reveal button, and add a separate Share button**

Locate the card action row that currently uses the `Share2` icon to open the reveal/copy dialog (around the existing reveal/copy button). The current button opens the reveal dialog — rename it to "Reveal" semantically and switch its icon to `Eye`. Then add a *new* Share button beside it gated by `canModify(cred)`. Example diff for the card actions block:

```tsx
<div className="flex gap-1">
  <Button
    size="sm"
    variant="ghost"
    className="h-7 w-7 p-0"
    onClick={() => openRevealDialog(cred)}
    aria-label="Reveal credential"
    title="Reveal"
  >
    <Eye className="h-3.5 w-3.5" />
  </Button>
  {canModify(cred) && (
    <Button
      size="sm"
      variant="ghost"
      className="h-7 w-7 p-0"
      onClick={() => setShareTarget(cred)}
      aria-label="Share credential"
      title="Share with team"
    >
      <Share2 className="h-3.5 w-3.5" />
    </Button>
  )}
  {canModify(cred) && (
    <Button
      size="sm"
      variant="ghost"
      className="h-7 w-7 p-0"
      onClick={() => openEditDialog(cred)}
      aria-label="Edit credential"
    >
      <Pencil className="h-3.5 w-3.5" />
    </Button>
  )}
  {canModify(cred) && (
    <Button
      size="sm"
      variant="ghost"
      className="h-7 w-7 p-0 text-destructive"
      onClick={() => openDeleteDialog(cred)}
      aria-label="Delete credential"
    >
      <Trash2 className="h-3.5 w-3.5" />
    </Button>
  )}
</div>
```

(Use the existing onClick handler names — the snippet above shows the structure; do not invent new handler names if the file already uses different ones. The two changes per card are: split Reveal from Share, and add `canModify(cred)` gates on Share/Edit/Delete.)

Also update the existing reveal dialog's header subtitle from `"Share these credentials securely"` to `"Reveal and copy credentials"` so the UI no longer claims to share.

- [ ] **Step 5: Render the dialog**

Near the bottom of the component's JSX, before the closing fragment/wrapper:

```tsx
{shareTarget && (
  <CredentialShareDialog
    open={!!shareTarget}
    onOpenChange={(o) => !o && setShareTarget(null)}
    credentialId={shareTarget.id}
    credentialLabel={shareTarget.label}
    members={members}
  />
)}
```

- [ ] **Step 6: Lint + dev server smoke test**

Run:

```bash
cd frontend
npm run lint
npm run dev
```

Open `http://localhost:3000/credentials`. Confirm:
- Each card now has a separate Reveal (eye) and Share (share2) icon.
- Reveal dialog subtitle reads "Reveal and copy credentials".
- As an owner: Share dialog opens; lists owners/managers as chips; lists current shared developers; can add a developer; can revoke.
- As a developer who is not the creator: Share/Edit/Delete icons are hidden on credentials they don't own.

- [ ] **Step 7: Commit**

```bash
cd ..
git add frontend/src/components/credentials-vault-client.tsx
git commit -m "feat(frontend): split reveal from share; gate writes by can_modify"
```

---

## Task 15: Manual end-to-end verification

- [ ] **Step 1: Backend up**

In one terminal:

```bash
.venv\Scripts\activate
python manage.py runserver
```

- [ ] **Step 2: Frontend up**

In another terminal:

```bash
cd frontend
npm run dev
```

- [ ] **Step 3: Walk the flow with two browser profiles**

1. As an **owner** account, open `/credentials`. Confirm every credential card shows Reveal + Share + Edit + Delete icons.
2. As a **developer** account in the same team:
   - Credentials that were already in the DB before the migration are visible (because the backfill auto-shared them).
   - Newly-created credentials by another developer are NOT visible.
3. As owner, open the Share dialog on a new credential, add the developer, save.
4. As developer, refresh — the credential now appears with Reveal but no Share/Edit/Delete.
5. As owner, open the dialog again and revoke. As developer, refresh — credential disappears.
6. Check the audit log endpoint (or DB) to confirm `credential.shared` and `credential.unshared` rows were written.

- [ ] **Step 4: No commit needed**

This task is verification only.

---

## Self-review notes

- Every spec section maps to a task: model + queryset (T2), permissions (T4), visibility filter swap (T5), serializers (T6), endpoints (T7), audit actions (T1), migration backfill (T2 step 5), frontend dialog (T12), proxy routes (T13), card wiring + write gating (T14), tests (T3 + T8 + T9), manual verification (T15).
- No placeholders. All file paths, code, and commands are concrete.
- Type/name consistency checked: `CredentialShare`, `CredentialShareSerializer`, `CredentialShareWriteSerializer`, `CredentialShareListCreateView`, `CredentialShareDeleteView`, `can_modify_credential`, `can_view_credential`, `visible_to`, `Credential.shares` reverse accessor, `created_by_id` field — all match across backend and frontend.
- The reveal endpoint already uses `visible_to(...).get(...)` so a shared developer can reveal (covered by `test_shared_dev_can_view_and_reveal`).
