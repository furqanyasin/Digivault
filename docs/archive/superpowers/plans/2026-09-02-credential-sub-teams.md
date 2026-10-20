# Credential Sub-Teams (Groups) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a team owner define named groups of people (Web Team, SEO Team), put each member in one group, and grant a whole group access to credentials, instead of sharing every credential with every person by hand.

**Architecture:** A `SubTeam` model under the tenant `Team`, a nullable `sub_team` FK on `TeamMembership`, and a `SubTeamCredentialGrant` table holding either a blanket rule (all credentials, or all of one credential type) or a single-credential grant. `Credential.objects.visible_to()` resolves grants at query time, so nothing is materialized into per-user rows and a credential created after the grant is covered immediately. Two pre-existing security holes in the reveal path are closed in the same first commit, because both would leak plaintext the moment groups reach `visible_to()`.

**Tech Stack:** Django 5.1, DRF, PostgreSQL, pytest + pytest-django, Next.js 16 (App Router) + React 19 + TypeScript + Tailwind v4.

**Spec:** [docs/superpowers/specs/2026-09-02-credential-sub-teams-design.md](../specs/2026-09-02-credential-sub-teams-design.md)

## Global Constraints

- **Owner-only writes.** Every group and grant write requires the owner membership: `_my_level(request.user, team) >= ROLE_LEVELS["owner"]`. A manager gets 403. This is deliberate and must not be softened, including the owner-lockout consequence.
- **`can_view_password` defaults to `False`** on grants, the opposite of `CredentialShare`.
- **Reveal rights are additive.** `can_view_password=False` is not a deny, it is a grant that omits reveal. If any share or any matching grant permits reveal, reveal is permitted.
- **Fail closed.** Every deletion path removes access and never adds it.
- **`pytest --create-db`** after Task 1, Task 2 and Task 4 (each adds a migration), per CLAUDE.md. `--reuse-db` will error out otherwise.
- **Envelope renderer.** All DRF responses are wrapped as `{data, errors, meta}` by `EnvelopeJSONRenderer`, but `response.data` in tests is the **raw payload**. Assert `resp.data["name"]`, never `resp.data["data"]["name"]`.
- **Frontend deploys separately from the backend.** Every new API field must be read defensively in TypeScript (optional in the type, `?? fallback` at the use site) so a frontend that ships first still renders.
- **No em dashes or en dashes in any user-facing copy** (labels, helper text, toasts, emails). They read as machine-written. Use commas, colons or parentheses.
- **Next.js 16 has breaking changes.** Before writing frontend code, read the relevant guide under `frontend/node_modules/next/dist/docs/`.
- Models inherit `BaseModel` (`apps/common/models.py`): UUID pk, `created_at`, `updated_at`, default ordering `-created_at`.

---

### Task 1: `SubTeam` model and the membership column

**Files:**
- Modify: `apps/accounts/models.py` (add `SubTeam` after `Team`, add `sub_team` + `clean()` to `TeamMembership` at ~line 137)
- Create: `apps/accounts/migrations/0013_subteam.py` (generated)
- Create: `tests/accounts/test_sub_teams.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `apps.accounts.models.SubTeam` with fields `team` (FK Team, related_name `sub_teams`), `name: str`, `description: str`. `TeamMembership.sub_team` (nullable FK to `SubTeam`, related_name `memberships`, `on_delete=SET_NULL`). `TeamMembership.clean()` raises `django.core.exceptions.ValidationError` keyed `"sub_team"` on a cross-team group.

- [ ] **Step 1: Write the failing tests**

Create `tests/accounts/test_sub_teams.py`:

```python
import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from apps.accounts.models import SubTeam, TeamMembership
from apps.accounts.services import TeamService


@pytest.fixture
def other_team(db, django_user_model):
    owner = django_user_model.objects.create_user(email="other@x.io", password="x")
    return TeamService.create(name="Other Agency", owner=owner)


@pytest.fixture
def member(db, django_user_model, team):
    u = django_user_model.objects.create_user(email="web1@x.io", password="x")
    return TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER
    )


def test_group_name_is_unique_within_a_team(team):
    SubTeam.objects.create(team=team, name="Web Team")
    with pytest.raises(IntegrityError):
        SubTeam.objects.create(team=team, name="Web Team")


def test_same_group_name_is_allowed_in_another_team(team, other_team):
    SubTeam.objects.create(team=team, name="Web Team")
    assert SubTeam.objects.create(team=other_team, name="Web Team").pk


def test_membership_rejects_a_group_from_another_team(team, other_team, member):
    foreign = SubTeam.objects.create(team=other_team, name="Web Team")
    member.sub_team = foreign
    with pytest.raises(ValidationError):
        member.full_clean()


def test_membership_accepts_a_group_from_its_own_team(team, member):
    member.sub_team = SubTeam.objects.create(team=team, name="Web Team")
    member.full_clean()  # must not raise
    member.save(update_fields=["sub_team"])
    member.refresh_from_db()
    assert member.sub_team.name == "Web Team"


def test_deleting_a_group_ungroups_its_members(team, member):
    member.sub_team = SubTeam.objects.create(team=team, name="Web Team")
    member.save(update_fields=["sub_team"])
    SubTeam.objects.filter(team=team, name="Web Team").delete()
    member.refresh_from_db()
    assert member.sub_team_id is None


def test_existing_memberships_start_ungrouped(member):
    assert member.sub_team_id is None
```

The `team` fixture comes from `tests/conftest.py` and is owned by the `user` fixture.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/accounts/test_sub_teams.py -v --create-db`
Expected: FAIL, `ImportError: cannot import name 'SubTeam'`.

- [ ] **Step 3: Add the model and the column**

In `apps/accounts/models.py`, add the import at the top:

```python
from django.core.exceptions import ValidationError
```

Add `SubTeam` immediately after the `Team` class:

```python
class SubTeam(BaseModel):
    """A named group of people inside one tenant Team, e.g. "Web Team".

    Governs credential access only. Role and `feature_access` are untouched by
    group membership, so a viewer in a fully granted group is still a viewer.
    A member holds at most one group.
    """

    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="sub_teams"
    )
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"], name="subteam_unique_name_per_team"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.team_id})"
```

Add the field to `TeamMembership`, after `feature_access`:

```python
    # The credential-access group this member sits in. Nullable because the
    # owner and every membership predating groups have none, which keeps
    # `visible_to()` behaving exactly as it did before this column existed.
    sub_team = models.ForeignKey(
        "accounts.SubTeam",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="memberships",
    )
```

And add `clean()` to `TeamMembership`:

```python
    def clean(self):
        """Reject a group belonging to a different Team.

        No DB constraint can span the two tables, and a cross-team group is a
        privilege-escalation bug rather than untidy data, so it is refused
        here and again in the serializer (DRF does not call clean()).
        """
        super().clean()
        if self.sub_team_id and self.sub_team.team_id != self.team_id:
            raise ValidationError(
                {"sub_team": "That group belongs to a different team."}
            )
```

- [ ] **Step 4: Generate and inspect the migration**

Run: `python manage.py makemigrations accounts`
Expected: creates `apps/accounts/migrations/0013_subteam.py` with `CreateModel` for `SubTeam`, `AddField` for `TeamMembership.sub_team`, and `AddConstraint` for `subteam_unique_name_per_team`. Confirm there is **no** data migration and no `AlterField` on anything else.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/accounts/test_sub_teams.py -v --create-db`
Expected: 6 passed.

- [ ] **Step 6: Confirm nothing else regressed**

Run: `pytest tests/accounts tests/credentials -q --create-db`
Expected: all pass. The new column is `NULL` everywhere, so credential visibility is unchanged.

- [ ] **Step 7: Commit**

```bash
git add apps/accounts/models.py apps/accounts/migrations/0013_subteam.py tests/accounts/test_sub_teams.py
git commit -m "feat(accounts): add SubTeam and TeamMembership.sub_team"
```

---

### Task 2: `SubTeamCredentialGrant` model

**Files:**
- Modify: `apps/credentials/models.py` (add the model after `CredentialShare`, ~line 269)
- Create: `apps/credentials/migrations/0009_subteamcredentialgrant.py` (generated)
- Create: `tests/credentials/test_group_grants_model.py`

**Interfaces:**
- Consumes: `apps.accounts.models.SubTeam` (Task 1).
- Produces: `apps.credentials.models.SubTeamCredentialGrant` with nested `Scope` choices `ALL = "all"`, `CREDENTIAL_TYPE = "type"`, `CREDENTIAL = "credential"`; fields `sub_team`, `scope`, `credential_type`, `credential`, `can_view_password` (default `False`), `granted_by`; `clean()` raising `ValidationError`.

- [ ] **Step 1: Write the failing tests**

Create `tests/credentials/test_group_grants_model.py`:

```python
import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from apps.accounts.models import SubTeam
from apps.accounts.services import TeamService
from apps.credentials.models import SubTeamCredentialGrant
from apps.credentials.services import CredentialService


@pytest.fixture
def group(db, team):
    return SubTeam.objects.create(team=team, name="Web Team")


@pytest.fixture
def credential(db, team):
    return CredentialService.create(
        team=team, website=None, label="cPanel", credential_type="cpanel",
        login_url="", username="u", password="p", notes="", created_by=None,
    )


def test_grant_defaults_to_no_reveal(group):
    grant = SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    assert grant.can_view_password is False


def test_only_one_blanket_grant_per_group(group):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    with pytest.raises(IntegrityError):
        SubTeamCredentialGrant.objects.create(
            sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
        )


def test_type_grant_is_unique_per_group_and_type(group):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE,
        credential_type="cpanel",
    )
    with pytest.raises(IntegrityError):
        SubTeamCredentialGrant.objects.create(
            sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE,
            credential_type="cpanel",
        )


def test_blanket_grant_rejects_a_target(group, credential):
    grant = SubTeamCredentialGrant(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL,
        credential=credential,
    )
    with pytest.raises(ValidationError):
        grant.full_clean()


def test_type_grant_requires_a_credential_type(group):
    grant = SubTeamCredentialGrant(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE
    )
    with pytest.raises(ValidationError):
        grant.full_clean()


def test_credential_grant_requires_a_credential(group):
    grant = SubTeamCredentialGrant(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL
    )
    with pytest.raises(ValidationError):
        grant.full_clean()


def test_credential_grant_rejects_a_credential_from_another_team(group, django_user_model):
    other_owner = django_user_model.objects.create_user(email="o2@x.io", password="x")
    other_team = TeamService.create(name="Other", owner=other_owner)
    foreign = CredentialService.create(
        team=other_team, website=None, label="Foreign", credential_type="cpanel",
        login_url="", username="u", password="p", notes="", created_by=None,
    )
    grant = SubTeamCredentialGrant(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL,
        credential=foreign,
    )
    with pytest.raises(ValidationError):
        grant.full_clean()


def test_deleting_the_credential_removes_its_grant(group, credential):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL,
        credential=credential,
    )
    credential.delete()
    assert not SubTeamCredentialGrant.objects.exists()


def test_deleting_the_group_removes_its_grants(group):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    group.delete()
    assert not SubTeamCredentialGrant.objects.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/credentials/test_group_grants_model.py -v --create-db`
Expected: FAIL, `ImportError: cannot import name 'SubTeamCredentialGrant'`.

- [ ] **Step 3: Add the model**

In `apps/credentials/models.py`, add the import at the top:

```python
from django.core.exceptions import ValidationError
```

Add after `CredentialShare`:

```python
class SubTeamCredentialGrant(BaseModel):
    """Grants a SubTeam access to credentials. Created by the team owner only.

    Three scopes: every credential in the team, every credential of one
    `credential_type`, or one specific credential. `can_view_password` defaults
    to False, deliberately the opposite of `CredentialShare`, so a grant is
    use-only until the owner widens it on purpose.

    Grants are resolved at query time by `CredentialQuerySet.visible_to`, never
    expanded into per-user rows: a credential created after the grant is
    covered immediately, and moving a member out of the group revokes on their
    next request.
    """

    class Scope(models.TextChoices):
        ALL = "all", "All credentials"
        CREDENTIAL_TYPE = "type", "All credentials of a type"
        CREDENTIAL = "credential", "A single credential"

    sub_team = models.ForeignKey(
        "accounts.SubTeam",
        on_delete=models.CASCADE,
        related_name="credential_grants",
    )
    scope = models.CharField(max_length=12, choices=Scope.choices)
    # Set only when scope == CREDENTIAL_TYPE.
    credential_type = models.CharField(max_length=30, blank=True, default="")
    # Set only when scope == CREDENTIAL.
    credential = models.ForeignKey(
        Credential,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sub_team_grants",
    )
    can_view_password = models.BooleanField(default=False)
    granted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credential_grants_granted",
    )

    class Meta:
        ordering = ["scope", "credential_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["sub_team"],
                condition=Q(scope="all"),
                name="grant_one_blanket_per_subteam",
            ),
            models.UniqueConstraint(
                fields=["sub_team", "credential_type"],
                condition=Q(scope="type"),
                name="grant_unique_type_per_subteam",
            ),
            models.UniqueConstraint(
                fields=["sub_team", "credential"],
                condition=Q(scope="credential"),
                name="grant_unique_credential_per_subteam",
            ),
        ]
        indexes = [
            models.Index(fields=["sub_team", "scope"], name="grant_subteam_scope_idx"),
        ]

    def __str__(self) -> str:
        target = {
            self.Scope.ALL: "all credentials",
            self.Scope.CREDENTIAL_TYPE: f"type={self.credential_type}",
            self.Scope.CREDENTIAL: f"credential={self.credential_id}",
        }.get(self.scope, self.scope)
        return f"{self.sub_team_id} -> {target}"

    def clean(self):
        """Exactly the field matching `scope` is set, and no cross-team target.

        Also enforced in the serializer, because DRF never calls clean().
        """
        super().clean()
        if self.scope == self.Scope.ALL:
            if self.credential_type or self.credential_id:
                raise ValidationError(
                    "A grant covering all credentials takes no target."
                )
        elif self.scope == self.Scope.CREDENTIAL_TYPE:
            if not self.credential_type:
                raise ValidationError(
                    {"credential_type": "Required for a credential-type grant."}
                )
            if self.credential_id:
                raise ValidationError(
                    {"credential": "Not allowed on a credential-type grant."}
                )
        elif self.scope == self.Scope.CREDENTIAL:
            if not self.credential_id:
                raise ValidationError(
                    {"credential": "Required for a single-credential grant."}
                )
            if self.credential_type:
                raise ValidationError(
                    {"credential_type": "Not allowed on a single-credential grant."}
                )
            if self.credential.team_id != self.sub_team.team_id:
                raise ValidationError(
                    {"credential": "That credential belongs to a different team."}
                )
```

`Q` is already imported at the top of this module.

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations credentials`
Expected: `apps/credentials/migrations/0009_subteamcredentialgrant.py` with one `CreateModel`, three `AddConstraint`, one `AddIndex`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/credentials/test_group_grants_model.py -v --create-db`
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/credentials/models.py apps/credentials/migrations/0009_subteamcredentialgrant.py tests/credentials/test_group_grants_model.py
git commit -m "feat(credentials): add SubTeamCredentialGrant"
```

---

### Task 3: Resolve group grants in `visible_to()`

**Files:**
- Modify: `apps/credentials/models.py` (`CredentialQuerySet.visible_to`, ~line 38)
- Create: `tests/credentials/test_group_access.py`

**Interfaces:**
- Consumes: `SubTeamCredentialGrant` (Task 2), `TeamMembership.sub_team` (Task 1).
- Produces: `CredentialQuerySet._group_grant_q(user) -> django.db.models.Q | None`, returning `None` when the user is in no group or the group holds no usable grants.

- [ ] **Step 1: Write the failing tests**

Create `tests/credentials/test_group_access.py`:

```python
import pytest

from apps.accounts.models import SubTeam, TeamMembership
from apps.credentials.models import Credential, SubTeamCredentialGrant
from apps.credentials.services import CredentialService


@pytest.fixture
def group(db, team):
    return SubTeam.objects.create(team=team, name="Web Team")


@pytest.fixture
def grouped_dev(db, django_user_model, team, group):
    u = django_user_model.objects.create_user(email="webdev@x.io", password="x")
    TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER, sub_team=group
    )
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u


def _make_cred(team, label="cPanel", credential_type="cpanel"):
    return CredentialService.create(
        team=team, website=None, label=label, credential_type=credential_type,
        login_url="", username="u", password="p", notes="", created_by=None,
    )


def test_ungrouped_developer_sees_nothing(team, django_user_model):
    dev = django_user_model.objects.create_user(email="plain@x.io", password="x")
    TeamMembership.objects.create(user=dev, team=team, role=TeamMembership.Role.DEVELOPER)
    _make_cred(team)
    assert not Credential.objects.visible_to(dev).exists()


def test_grouped_developer_with_no_grant_sees_nothing(team, grouped_dev):
    _make_cred(team)
    assert not Credential.objects.visible_to(grouped_dev).exists()


def test_blanket_grant_shows_every_credential(team, group, grouped_dev):
    _make_cred(team, "cPanel", "cpanel")
    _make_cred(team, "WP", "wordpress")
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    assert Credential.objects.visible_to(grouped_dev).count() == 2


def test_blanket_grant_covers_a_credential_created_afterwards(team, group, grouped_dev):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    later = _make_cred(team, "Added later", "ftp")
    assert Credential.objects.visible_to(grouped_dev).filter(pk=later.pk).exists()


def test_type_grant_matches_only_that_type(team, group, grouped_dev):
    cpanel = _make_cred(team, "cPanel", "cpanel")
    _make_cred(team, "WP", "wordpress")
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE,
        credential_type="cpanel",
    )
    visible = Credential.objects.visible_to(grouped_dev)
    assert list(visible.values_list("pk", flat=True)) == [cpanel.pk]


def test_single_credential_grant_matches_only_that_credential(team, group, grouped_dev):
    one = _make_cred(team, "One", "cpanel")
    _make_cred(team, "Two", "cpanel")
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL, credential=one,
    )
    visible = Credential.objects.visible_to(grouped_dev)
    assert list(visible.values_list("pk", flat=True)) == [one.pk]


def test_removing_the_member_from_the_group_revokes_access(team, group, grouped_dev):
    _make_cred(team)
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    assert Credential.objects.visible_to(grouped_dev).exists()
    TeamMembership.objects.filter(user=grouped_dev).update(sub_team=None)
    assert not Credential.objects.visible_to(grouped_dev).exists()


def test_deleting_the_group_revokes_access(team, group, grouped_dev):
    _make_cred(team)
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    group.delete()
    assert not Credential.objects.visible_to(grouped_dev).exists()


def test_a_grant_never_leaks_across_teams(team, group, grouped_dev, django_user_model):
    from apps.accounts.services import TeamService

    other_owner = django_user_model.objects.create_user(email="o3@x.io", password="x")
    other_team = TeamService.create(name="Other", owner=other_owner)
    foreign = _make_cred(other_team, "Foreign", "cpanel")
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    assert not Credential.objects.visible_to(grouped_dev).filter(pk=foreign.pk).exists()


def test_no_duplicate_rows_when_two_grants_overlap(team, group, grouped_dev):
    cred = _make_cred(team, "cPanel", "cpanel")
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL, credential=cred,
    )
    assert Credential.objects.visible_to(grouped_dev).count() == 1


def test_extension_lookup_honours_a_group_grant(team, group, grouped_dev):
    """The extension reads the same visible_to gate, in both of its modes."""
    from rest_framework.test import APIClient

    cred = _make_cred(team, "cPanel", "cpanel")
    cred.login_url = "https://client.example.com/cpanel"
    cred.save(update_fields=["login_url"])
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    grouped_dev.set_password("SecurePass1!")
    grouped_dev.save(update_fields=["password"])

    client = APIClient()
    token = client.post(
        "/api/v1/auth/token/",
        {"email": grouped_dev.email, "password": "SecurePass1!"},
        format="json",
    ).data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    all_items = client.get("/api/extension/credentials/?all=1")
    assert [c["id"] for c in all_items.data] == [str(cred.pk)]

    by_domain = client.get("/api/extension/credentials/?domain=client.example.com")
    assert [c["id"] for c in by_domain.data] == [str(cred.pk)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/credentials/test_group_access.py -v --create-db`
Expected: the first two pass (nobody can see anything yet), the rest FAIL on assertion because grants are not consulted.

- [ ] **Step 3: Add the fourth branch**

Replace `CredentialQuerySet.visible_to` in `apps/credentials/models.py`:

```python
    def visible_to(self, user):
        if user is None or not user.is_authenticated:
            return self.none()

        from apps.accounts.models import TeamMembership

        privileged_team_ids = TeamMembership.objects.filter(
            user=user,
            role__in=[TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER],
        ).values_list("team_id", flat=True)

        access = (
            Q(team_id__in=privileged_team_ids)
            | Q(created_by=user)
            | Q(shares__user=user)
        )
        group_access = self._group_grant_q(user)
        if group_access is not None:
            access |= group_access
        return self.filter(access).distinct()

    @staticmethod
    def _group_grant_q(user):
        """Q matching the credentials this user's group has been granted.

        Returns None when the user is in no group, or their group holds no
        grants, so the caller leaves the filter untouched rather than OR-ing an
        empty Q (which matches everything).

        Two small indexed reads feed the Q instead of one nested subquery.
        `visible_to` is the only gate in front of the entire vault, so
        readability here is worth the extra query.
        """
        from apps.accounts.models import TeamMembership

        sub_team_ids = list(
            TeamMembership.objects.filter(user=user)
            .exclude(sub_team_id=None)
            .values_list("sub_team_id", flat=True)
        )
        if not sub_team_ids:
            return None

        grants = SubTeamCredentialGrant.objects.filter(
            sub_team_id__in=sub_team_ids
        ).values_list(
            "scope", "credential_type", "credential_id", "sub_team__team_id"
        )

        q = Q()
        matched = False
        for scope, credential_type, credential_id, team_id in grants:
            if scope == SubTeamCredentialGrant.Scope.ALL:
                q |= Q(team_id=team_id)
            elif scope == SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE:
                q |= Q(team_id=team_id, credential_type=credential_type)
            elif scope == SubTeamCredentialGrant.Scope.CREDENTIAL:
                # Scoped by pk, and the model's clean() already refuses a
                # credential from another team.
                q |= Q(pk=credential_id)
            else:
                # An unknown scope grants nothing. Fail closed.
                continue
            matched = True
        return q if matched else None
```

`SubTeamCredentialGrant` is defined later in this module, so it resolves at call time, not import time. That is fine for a method body but do **not** move the reference to module level.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/credentials/test_group_access.py -v --create-db`
Expected: 11 passed.

- [ ] **Step 5: Confirm the existing visibility rules are untouched**

Run: `pytest tests/credentials -q --create-db`
Expected: all pass, including `test_visibility.py` and `test_sharing.py`.

- [ ] **Step 6: Commit**

```bash
git add apps/credentials/models.py tests/credentials/test_group_access.py
git commit -m "feat(credentials): resolve sub-team grants in visible_to"
```

---

### Task 4: Close both reveal holes

This task carries the security value of the whole feature. It must land before any API or UI exists, so the group path never ships in a leaking state.

**Files:**
- Modify: `apps/credentials/services.py` (`can_view_password` ~line 95, `reveal` ~line 119)
- Modify: `apps/credentials/models.py` (`CredentialAccessLog.Action`, ~line 199)
- Modify: `apps/credentials/views.py` (`CredentialRevealView` ~line 234, add `ExtensionCredentialRevealView`)
- Modify: `apps/credentials/extension_urls.py`
- Modify: `extension/background.js:275-278`
- Create: `apps/credentials/migrations/0010_credentialaccesslog_autofill.py` (generated)
- Create: `tests/credentials/test_group_reveal.py`

**Interfaces:**
- Consumes: `SubTeamCredentialGrant` (Task 2).
- Produces: `CredentialAccessLog.Action.AUTOFILL == "autofill"`. `CredentialService.can_view_password(credential, user) -> bool`, closed by default. `ExtensionCredentialRevealView` at `POST /api/extension/credentials/<uuid:pk>/reveal/`, url name `extension-credential-reveal`.

- [ ] **Step 1: Write the failing tests**

Create `tests/credentials/test_group_reveal.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamMembership
from apps.credentials.models import (
    Credential, CredentialAccessLog, CredentialShare, SubTeamCredentialGrant,
)
from apps.credentials.services import CredentialService


@pytest.fixture
def group(db, team):
    return SubTeam.objects.create(team=team, name="Web Team")


def _member(django_user_model, team, email, role, group=None):
    u = django_user_model.objects.create_user(email=email, password="SecurePass1!")
    TeamMembership.objects.create(user=u, team=team, role=role, sub_team=group)
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u


def _client_for(user):
    c = APIClient()
    resp = c.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SecurePass1!"},
        format="json",
    )
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


@pytest.fixture
def credential(db, team):
    return CredentialService.create(
        team=team, website=None, label="cPanel", credential_type="cpanel",
        login_url="", username="u", password="s3cret", notes="", created_by=None,
    )


@pytest.fixture
def no_reveal_dev(db, django_user_model, team, group, credential):
    dev = _member(django_user_model, team, "webdev@x.io", TeamMembership.Role.DEVELOPER, group)
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL, can_view_password=False,
    )
    return dev


def test_no_reveal_grantee_gets_a_blanked_password(no_reveal_dev, credential):
    resp = _client_for(no_reveal_dev).post(f"/api/v1/credentials/{credential.pk}/reveal/")
    assert resp.status_code == 200
    assert resp.data["password"] == ""
    assert resp.data["password_hidden"] is True
    assert resp.data["username"] == "u"


def test_for_autofill_query_param_no_longer_bypasses_the_dashboard(no_reveal_dev, credential):
    resp = _client_for(no_reveal_dev).post(
        f"/api/v1/credentials/{credential.pk}/reveal/?for_autofill=1"
    )
    assert resp.data["password"] == ""
    assert resp.data["password_hidden"] is True


def test_for_autofill_body_flag_no_longer_bypasses_the_dashboard(no_reveal_dev, credential):
    resp = _client_for(no_reveal_dev).post(
        f"/api/v1/credentials/{credential.pk}/reveal/",
        {"for_autofill": True}, format="json",
    )
    assert resp.data["password"] == ""
    assert resp.data["password_hidden"] is True


def test_reveal_grant_returns_the_password(db, django_user_model, team, group, credential):
    dev = _member(django_user_model, team, "lead@x.io", TeamMembership.Role.DEVELOPER, group)
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL, can_view_password=True,
    )
    resp = _client_for(dev).post(f"/api/v1/credentials/{credential.pk}/reveal/")
    assert resp.data["password"] == "s3cret"
    assert resp.data["password_hidden"] is False


def test_a_permissive_grant_wins_over_a_restrictive_share(
    db, django_user_model, team, group, credential
):
    """can_view_password=False is not a deny. Access is additive."""
    dev = _member(django_user_model, team, "both@x.io", TeamMembership.Role.DEVELOPER, group)
    CredentialShare.objects.create(credential=credential, user=dev, can_view_password=False)
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL, can_view_password=True,
    )
    resp = _client_for(dev).post(f"/api/v1/credentials/{credential.pk}/reveal/")
    assert resp.data["password"] == "s3cret"


def test_viewer_in_a_granted_group_still_cannot_reveal(
    db, django_user_model, team, group, credential
):
    viewer = _member(django_user_model, team, "viewer@x.io", TeamMembership.Role.VIEWER, group)
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL, can_view_password=True,
    )
    resp = _client_for(viewer).post(f"/api/v1/credentials/{credential.pk}/reveal/")
    assert resp.status_code in (403, 400)


def test_owner_manager_and_creator_reveal_as_before(db, django_user_model, team, user):
    """Pins the can_view_password fallback flip from True to False as a no-op."""
    cred = CredentialService.create(
        team=team, website=None, label="X", credential_type="cpanel",
        login_url="", username="u", password="s3cret", notes="", created_by=None,
    )
    assert CredentialService.can_view_password(cred, user) is True  # owner
    mgr = _member(django_user_model, team, "mgr@x.io", TeamMembership.Role.MANAGER)
    assert CredentialService.can_view_password(cred, mgr) is True
    creator = _member(django_user_model, team, "c@x.io", TeamMembership.Role.DEVELOPER)
    mine = CredentialService.create(
        team=team, website=None, label="Mine", credential_type="cpanel",
        login_url="", username="u", password="p", notes="", created_by=creator,
    )
    assert CredentialService.can_view_password(mine, creator) is True


def test_a_stranger_cannot_view_the_password(db, django_user_model, team, credential):
    dev = _member(django_user_model, team, "stranger@x.io", TeamMembership.Role.DEVELOPER)
    assert CredentialService.can_view_password(credential, dev) is False


def test_extension_route_returns_plaintext_and_logs_autofill(no_reveal_dev, credential):
    resp = _client_for(no_reveal_dev).post(
        f"/api/extension/credentials/{credential.pk}/reveal/"
    )
    assert resp.status_code == 200
    assert resp.data["password"] == "s3cret"
    assert CredentialAccessLog.objects.filter(
        credential=credential, user=no_reveal_dev,
        action=CredentialAccessLog.Action.AUTOFILL,
    ).exists()


def test_dashboard_reveal_logs_viewed_not_autofill(no_reveal_dev, credential):
    _client_for(no_reveal_dev).post(f"/api/v1/credentials/{credential.pk}/reveal/")
    assert CredentialAccessLog.objects.filter(
        credential=credential, action=CredentialAccessLog.Action.VIEWED
    ).exists()
    assert not CredentialAccessLog.objects.filter(
        action=CredentialAccessLog.Action.AUTOFILL
    ).exists()


def test_extension_route_404s_on_a_credential_the_caller_cannot_see(
    db, django_user_model, team, credential
):
    dev = _member(django_user_model, team, "nope@x.io", TeamMembership.Role.DEVELOPER)
    resp = _client_for(dev).post(f"/api/extension/credentials/{credential.pk}/reveal/")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/credentials/test_group_reveal.py -v --create-db`
Expected: FAIL. The `for_autofill` bypass tests return `s3cret`, and the extension route 404s on the URL itself.

- [ ] **Step 3: Add the `AUTOFILL` log action**

In `apps/credentials/models.py`, inside `CredentialAccessLog.Action`:

```python
        # Distinct from VIEWED so an autofill pull of a password the dashboard
        # would have hidden is attributable. See the reveal notes in
        # docs/superpowers/specs/2026-09-02-credential-sub-teams-design.md.
        AUTOFILL = "autofill", "Autofilled by the extension"
```

- [ ] **Step 4: Rewrite `can_view_password`**

Replace the method in `apps/credentials/services.py`:

```python
    @classmethod
    def can_view_password(cls, credential: Credential, user) -> bool:
        """Whether `user` may see this credential's plaintext password.

        Closed by default. The old version ended `return share.can_view_password
        if share else True`, which was survivable only because the sole routes
        into reveal were owner, manager, creator and an explicit share. Group
        grants add a fourth route, and that fallback would have handed every
        grantee full plaintext.

        Access is additive: `can_view_password=False` is not a deny, it is a
        grant that omits reveal, so any permitting row wins.
        """
        from apps.credentials.models import CredentialShare, SubTeamCredentialGrant

        if credential.created_by_id == getattr(user, "id", None):
            return True

        membership = TeamMembership.objects.filter(
            user=user, team=credential.team
        ).first()
        if membership and membership.role in (
            TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER
        ):
            return True

        if CredentialShare.objects.filter(
            credential=credential, user=user, can_view_password=True
        ).exists():
            return True

        if membership and membership.sub_team_id:
            permitting = SubTeamCredentialGrant.objects.filter(
                sub_team_id=membership.sub_team_id, can_view_password=True
            )
            if permitting.filter(scope=SubTeamCredentialGrant.Scope.ALL).exists():
                return True
            if permitting.filter(
                scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE,
                credential_type=credential.credential_type,
            ).exists():
                return True
            if permitting.filter(
                scope=SubTeamCredentialGrant.Scope.CREDENTIAL,
                credential_id=credential.pk,
            ).exists():
                return True

        return False
```

- [ ] **Step 5: Record the autofill action in `reveal`**

In `CredentialService.reveal`, replace the `CredentialAccessLog.objects.create(...)` call:

```python
        CredentialAccessLog.objects.create(
            credential=credential,
            user=requesting_user,
            action=(
                CredentialAccessLog.Action.AUTOFILL
                if for_autofill
                else CredentialAccessLog.Action.VIEWED
            ),
            ip_address=ip_address,
        )
```

- [ ] **Step 6: Stop trusting `for_autofill` on the dashboard endpoint**

In `apps/credentials/views.py`, delete the `for_autofill = (...)` block from `CredentialRevealView.post` and call `CredentialService.reveal` without that argument, so it keeps its `False` default:

```python
        revealed = CredentialService.reveal(
            credential=credential,
            requesting_user=request.user,
            ip_address=_get_client_ip(request),
        )
```

Update the class docstring:

```python
class CredentialRevealView(APIView):
    """POST /api/v1/credentials/<pk>/reveal/

    The dashboard reveal. Always honours `can_view_password`, so a caller whose
    only access is a no-reveal share or grant gets `password_hidden` and an
    empty string. `for_autofill` is deliberately NOT read from the request:
    it used to be, which let anyone append `?for_autofill=1` and read a
    password they were not meant to see. Autofill lives on
    ExtensionCredentialRevealView instead. Every call is audit-logged.
    Viewer role is blocked at the service layer.
    """
```

- [ ] **Step 7: Add the extension reveal view**

Append to `apps/credentials/views.py`:

```python
class ExtensionCredentialRevealView(APIView):
    """POST /api/extension/credentials/<pk>/reveal/

    The autofill path. Returns plaintext even when the caller's only access is
    a no-reveal share or grant, because the extension has to put the password
    into the login form.

    This is not a security boundary and must not be described as one: the
    extension carries the same JWT as the dashboard, so a determined user can
    call this route themselves. What it buys is that the password is never
    rendered in the dashboard, there is no one-parameter toggle on the
    dashboard endpoint, and every autofill pull is logged as AUTOFILL against a
    named user. Control by accountability.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        try:
            credential = (
                Credential.objects.visible_to(request.user).get(pk=pk, team=team)
            )
        except Credential.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        revealed = CredentialService.reveal(
            credential=credential,
            requesting_user=request.user,
            ip_address=_get_client_ip(request),
            for_autofill=True,
        )
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_REVEALED,
            description=f"Autofilled credential '{credential.label}'",
            resource_type="credential", resource_id=credential.pk,
            metadata={**site_meta(credential), "autofill": True},
        )
        return Response(RevealedCredentialSerializer(revealed).data)
```

In `apps/credentials/extension_urls.py`, add the import and the route:

```python
from apps.credentials.views import (
    ExtensionCredentialLookupView,
    ExtensionCredentialRevealView,
    ExtensionCredentialSaveView,
    WebHandoffView,
    WebHandoffExchangeView,
)
```

```python
    path(
        "credentials/<uuid:pk>/reveal/",
        ExtensionCredentialRevealView.as_view(),
        name="extension-credential-reveal",
    ),
```

Place it **before** `credentials/save/` is irrelevant (the patterns do not overlap), but keep it next to the other credential routes for readability.

- [ ] **Step 8: Generate the migration for the new log choice**

Run: `python manage.py makemigrations credentials`
Expected: `apps/credentials/migrations/0010_alter_credentialaccesslog_action.py`, a single `AlterField`. `max_length` is already 20 and `"autofill"` is 8 characters, so no length change is needed.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `pytest tests/credentials/test_group_reveal.py -v --create-db`
Expected: 11 passed.

- [ ] **Step 10: Point the extension at the new route**

In `extension/background.js`, replace the reveal fetch at ~line 275:

```javascript
  // The autofill reveal. A share or grant with can_view_password=false still
  // needs the real password to fill the form, so this route returns it and
  // logs the pull as AUTOFILL. The dashboard endpoint no longer honours a
  // for_autofill flag.
  const res = await fetch(
    `${apiBase}/api/extension/credentials/${credentialId}/reveal/`,
```

Keep the rest of the call (method, headers, body) exactly as it is.

- [ ] **Step 11: Verify nothing else regressed**

Run: `pytest tests/credentials tests/accounts -q --create-db`
Expected: all pass. Pay attention to `test_extension_credentials.py` and `test_access_log_permissions.py`.

- [ ] **Step 12: Commit**

```bash
git add apps/credentials/services.py apps/credentials/models.py apps/credentials/views.py apps/credentials/extension_urls.py apps/credentials/migrations/0010_alter_credentialaccesslog_action.py extension/background.js tests/credentials/test_group_reveal.py
git commit -m "fix(credentials): close fail-open password check and for_autofill bypass"
```

---

### Task 5: Groups API and group assignment on members

**Files:**
- Modify: `apps/audit/models.py` (`ActivityLog.Action`)
- Create: `apps/audit/migrations/0010_alter_activitylog_action.py` (generated)
- Modify: `apps/accounts/serializers.py` (add `SubTeamSerializer`, extend `TeamMembershipSerializer`)
- Modify: `apps/accounts/views.py` (add `_require_owner`, `SubTeamListCreateView`, `SubTeamDetailView`; extend `TeamMemberDetailView.patch` and `TeamCreateUserView.post`)
- Modify: `apps/accounts/urls.py`
- Create: `tests/accounts/test_sub_teams_api.py`

**Interfaces:**
- Consumes: `SubTeam` (Task 1).
- Produces: `_require_owner(request, team) -> Response | None`; url names `sub-team-list-create`, `sub-team-detail`; `TeamMembershipSerializer` fields `sub_team` (UUID or null) and `sub_team_name` (str), both read-only.

- [ ] **Step 1: Write the failing tests**

Create `tests/accounts/test_sub_teams_api.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamMembership


def _client_for(user):
    c = APIClient()
    resp = c.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SecurePass1!"},
        format="json",
    )
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


@pytest.fixture
def manager(db, django_user_model, team):
    u = django_user_model.objects.create_user(email="mgr@x.io", password="SecurePass1!")
    TeamMembership.objects.create(user=u, team=team, role=TeamMembership.Role.MANAGER)
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u


def test_owner_creates_a_group(auth_client, team):
    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/",
        {"name": "Web Team", "description": "Builds and maintains sites"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["name"] == "Web Team"
    assert resp.data["member_count"] == 0


def test_manager_cannot_create_a_group(manager, team):
    resp = _client_for(manager).post(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/", {"name": "Web Team"}, format="json",
    )
    assert resp.status_code == 403


def test_manager_can_list_groups(manager, team):
    SubTeam.objects.create(team=team, name="Web Team")
    resp = _client_for(manager).get(f"/api/v1/auth/teams/{team.pk}/sub-teams/")
    assert resp.status_code == 200
    assert [g["name"] for g in resp.data] == ["Web Team"]


def test_duplicate_group_name_is_rejected(auth_client, team):
    SubTeam.objects.create(team=team, name="Web Team")
    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/", {"name": "Web Team"}, format="json",
    )
    assert resp.status_code == 400


def test_owner_renames_a_group(auth_client, team):
    group = SubTeam.objects.create(team=team, name="Web Team")
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/{group.pk}/",
        {"name": "Website Team"}, format="json",
    )
    assert resp.status_code == 200
    assert resp.data["name"] == "Website Team"


def test_manager_cannot_rename_or_delete_a_group(manager, team):
    group = SubTeam.objects.create(team=team, name="Web Team")
    client = _client_for(manager)
    url = f"/api/v1/auth/teams/{team.pk}/sub-teams/{group.pk}/"
    assert client.patch(url, {"name": "X"}, format="json").status_code == 403
    assert client.delete(url).status_code == 403


def test_owner_deletes_a_group_and_members_are_ungrouped(auth_client, team, django_user_model):
    group = SubTeam.objects.create(team=team, name="Web Team")
    u = django_user_model.objects.create_user(email="d@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER, sub_team=group
    )
    resp = auth_client.delete(f"/api/v1/auth/teams/{team.pk}/sub-teams/{group.pk}/")
    assert resp.status_code == 204
    m.refresh_from_db()
    assert m.sub_team_id is None


def test_a_group_from_another_team_is_not_reachable(auth_client, team, django_user_model):
    from apps.accounts.services import TeamService

    other_owner = django_user_model.objects.create_user(email="oo@x.io", password="x")
    other = TeamService.create(name="Other", owner=other_owner)
    foreign = SubTeam.objects.create(team=other, name="Web Team")
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/{foreign.pk}/",
        {"name": "Hijacked"}, format="json",
    )
    assert resp.status_code == 404


def test_owner_sets_a_group_when_creating_a_user(auth_client, team):
    group = SubTeam.objects.create(team=team, name="Web Team")
    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.pk}/users/",
        {
            "email": "new@x.io", "name": "New Dev",
            "role": "developer", "sub_team": str(group.pk),
        },
        format="json",
    )
    assert resp.status_code in (200, 201)
    membership = TeamMembership.objects.get(team=team, user__email="new@x.io")
    assert membership.sub_team_id == group.pk


def test_manager_cannot_set_a_group_when_creating_a_user(manager, team):
    group = SubTeam.objects.create(team=team, name="Web Team")
    resp = _client_for(manager).post(
        f"/api/v1/auth/teams/{team.pk}/users/",
        {
            "email": "new2@x.io", "name": "N", "role": "developer",
            "sub_team": str(group.pk),
        },
        format="json",
    )
    assert resp.status_code == 403
    assert not TeamMembership.objects.filter(user__email="new2@x.io").exists()


def test_manager_can_still_create_a_user_without_a_group(manager, team):
    resp = _client_for(manager).post(
        f"/api/v1/auth/teams/{team.pk}/users/",
        {"email": "new3@x.io", "name": "N", "role": "developer"},
        format="json",
    )
    assert resp.status_code in (200, 201)


def test_owner_moves_an_existing_member_between_groups(auth_client, team, django_user_model):
    web = SubTeam.objects.create(team=team, name="Web Team")
    seo = SubTeam.objects.create(team=team, name="SEO Team")
    u = django_user_model.objects.create_user(email="mv@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER, sub_team=web
    )
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "developer", "sub_team": str(seo.pk)}, format="json",
    )
    assert resp.status_code == 200
    m.refresh_from_db()
    assert m.sub_team_id == seo.pk
    assert resp.data["sub_team_name"] == "SEO Team"


def test_owner_can_clear_a_members_group(auth_client, team, django_user_model):
    web = SubTeam.objects.create(team=team, name="Web Team")
    u = django_user_model.objects.create_user(email="cl@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER, sub_team=web
    )
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "developer", "sub_team": None}, format="json",
    )
    assert resp.status_code == 200
    m.refresh_from_db()
    assert m.sub_team_id is None


def test_manager_cannot_change_a_members_group(manager, team, django_user_model):
    web = SubTeam.objects.create(team=team, name="Web Team")
    u = django_user_model.objects.create_user(email="nm@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER
    )
    resp = _client_for(manager).patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "developer", "sub_team": str(web.pk)}, format="json",
    )
    assert resp.status_code == 403
    m.refresh_from_db()
    assert m.sub_team_id is None


def test_manager_can_still_change_a_role_without_touching_the_group(manager, team, django_user_model):
    u = django_user_model.objects.create_user(email="rr@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER
    )
    resp = _client_for(manager).patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "viewer"}, format="json",
    )
    assert resp.status_code == 200
    m.refresh_from_db()
    assert m.role == "viewer"


def test_assigning_a_group_from_another_team_is_rejected(auth_client, team, django_user_model):
    from apps.accounts.services import TeamService

    other_owner = django_user_model.objects.create_user(email="ox@x.io", password="x")
    other = TeamService.create(name="Other", owner=other_owner)
    foreign = SubTeam.objects.create(team=other, name="Web Team")
    u = django_user_model.objects.create_user(email="xt@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER
    )
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "developer", "sub_team": str(foreign.pk)}, format="json",
    )
    assert resp.status_code == 400
    m.refresh_from_db()
    assert m.sub_team_id is None
```

`auth_client` is the owner client from `tests/conftest.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/accounts/test_sub_teams_api.py -v --create-db`
Expected: FAIL with 404s on `/sub-teams/`.

- [ ] **Step 3: Add the audit actions**

In `apps/audit/models.py`, inside `ActivityLog.Action`, under the `# Team` group:

```python
        TEAM_GROUP_CREATED = "team.group_created", "Group created"
        TEAM_GROUP_UPDATED = "team.group_updated", "Group updated"
        TEAM_GROUP_DELETED = "team.group_deleted", "Group deleted"
        TEAM_MEMBER_GROUP_CHANGED = "team.member_group_changed", "Member group changed"
```

And under the `# Credentials` group, for Task 6:

```python
        CREDENTIAL_GROUP_GRANTED = "credential.group_granted", "Credential granted to a group"
        CREDENTIAL_GROUP_REVOKED = "credential.group_revoked", "Group credential grant revoked"
```

All values are well under the field's `max_length=60`.

Run: `python manage.py makemigrations audit`
Expected: `apps/audit/migrations/0010_alter_activitylog_action.py`, a single `AlterField`.

- [ ] **Step 4: Add the serializers**

In `apps/accounts/serializers.py`, import `SubTeam` alongside the other models and add:

```python
class SubTeamSerializer(BaseModelSerializer):
    """A credential-access group. `team` is taken from the URL, never the body."""

    member_count = serializers.SerializerMethodField()

    class Meta:
        model = SubTeam
        fields = ("id", "name", "description", "member_count", "created_at")
        read_only_fields = ("id", "member_count", "created_at")

    def get_member_count(self, obj) -> int:
        return obj.memberships.count()
```

Extend `TeamMembershipSerializer`:

```python
class TeamMembershipSerializer(BaseModelSerializer):
    user = UserSerializer(read_only=True)
    totp_enabled = serializers.BooleanField(source="user.totp_enabled", read_only=True)
    effective_features = serializers.SerializerMethodField()
    # Credential-access group. Read-only here: it is written through the
    # owner-gated branches in TeamMemberDetailView and TeamCreateUserView, so
    # it can never be set by a manager PATCHing a role.
    sub_team = serializers.PrimaryKeyRelatedField(read_only=True)
    sub_team_name = serializers.CharField(
        source="sub_team.name", read_only=True, default=None
    )

    class Meta:
        model = TeamMembership
        fields = (
            "id", "user", "role", "feature_access", "effective_features",
            "totp_enabled", "sub_team", "sub_team_name", "created_at",
        )
        read_only_fields = ("id", "totp_enabled", "sub_team", "sub_team_name", "created_at")
```

- [ ] **Step 5: Add the owner gate and the group views**

In `apps/accounts/views.py`, add after `_my_level`:

```python
def _require_owner(request, team):
    """None when the caller owns `team`, otherwise a 403 Response.

    Group and grant writes are owner-only by design. A manager can already
    read every credential in the team, but must never be able to widen access
    for somebody else. See
    docs/superpowers/specs/2026-09-02-credential-sub-teams-design.md.
    """
    my_level, _ = _my_level(request.user, team)
    if my_level < ROLE_LEVELS["owner"]:
        return Response(
            {"detail": "Team owner required."}, status=status.HTTP_403_FORBIDDEN
        )
    return None
```

Add the two views (import `SubTeam` and `SubTeamSerializer` at the top):

```python
class SubTeamListCreateView(APIView):
    """GET/POST /api/v1/auth/teams/<team_pk>/sub-teams/

    Listing is open to any team member so the UI can render a member's group
    badge. Creating is owner-only.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _team_or_404(self, team_pk):
        return Team.objects.filter(pk=team_pk).first()

    def get(self, request, team_pk):
        team = self._team_or_404(team_pk)
        if team is None or not _my_level(request.user, team)[0]:
            return Response(status=status.HTTP_404_NOT_FOUND)
        groups = team.sub_teams.all()
        return Response(SubTeamSerializer(groups, many=True).data)

    def post(self, request, team_pk):
        team = self._team_or_404(team_pk)
        if team is None or not _my_level(request.user, team)[0]:
            return Response(status=status.HTTP_404_NOT_FOUND)
        err = _require_owner(request, team)
        if err:
            return err

        ser = SubTeamSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        name = ser.validated_data["name"].strip()
        if not name:
            return Response(
                {"detail": "Group name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if SubTeam.objects.filter(team=team, name__iexact=name).exists():
            return Response(
                {"detail": f"A group called '{name}' already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        group = SubTeam.objects.create(
            team=team, name=name,
            description=ser.validated_data.get("description", ""),
        )
        AuditService.log(
            actor=request.user, action=ActivityLog.Action.TEAM_GROUP_CREATED,
            team=team, description=f"Created group '{group.name}'",
            resource_type="sub_team", resource_id=str(group.pk),
        )
        return Response(
            SubTeamSerializer(group).data, status=status.HTTP_201_CREATED
        )


class SubTeamDetailView(APIView):
    """PATCH/DELETE /api/v1/auth/teams/<team_pk>/sub-teams/<pk>/ — owner only.

    Deleting a group sets its members' `sub_team` to NULL (SET_NULL) and
    cascades its grants away, so members drop back to their own credentials
    plus individual shares. Access can only narrow.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _get(self, request, team_pk, pk):
        team = Team.objects.filter(pk=team_pk).first()
        if team is None or not _my_level(request.user, team)[0]:
            return None, None, Response(status=status.HTTP_404_NOT_FOUND)
        err = _require_owner(request, team)
        if err:
            return None, None, err
        group = SubTeam.objects.filter(pk=pk, team=team).first()
        if group is None:
            return None, None, Response(status=status.HTTP_404_NOT_FOUND)
        return team, group, None

    def patch(self, request, team_pk, pk):
        team, group, err = self._get(request, team_pk, pk)
        if err:
            return err
        name = (request.data.get("name") or group.name).strip()
        if not name:
            return Response(
                {"detail": "Group name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if SubTeam.objects.filter(team=team, name__iexact=name).exclude(pk=group.pk).exists():
            return Response(
                {"detail": f"A group called '{name}' already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        old_name = group.name
        group.name = name
        if "description" in request.data:
            group.description = request.data.get("description") or ""
        group.save(update_fields=["name", "description", "updated_at"])
        AuditService.log(
            actor=request.user, action=ActivityLog.Action.TEAM_GROUP_UPDATED,
            team=team, description=f"Renamed group '{old_name}' to '{group.name}'",
            resource_type="sub_team", resource_id=str(group.pk),
        )
        return Response(SubTeamSerializer(group).data)

    def delete(self, request, team_pk, pk):
        team, group, err = self._get(request, team_pk, pk)
        if err:
            return err
        name = group.name
        member_count = group.memberships.count()
        group.delete()
        AuditService.log(
            actor=request.user, action=ActivityLog.Action.TEAM_GROUP_DELETED,
            team=team,
            description=f"Deleted group '{name}', ungrouping {member_count} member(s)",
            resource_type="sub_team", resource_id=str(pk),
            metadata={"members_ungrouped": member_count},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 6: Accept `sub_team` on member PATCH**

Add a shared resolver above `TeamMemberDetailView` in `apps/accounts/views.py`:

```python
def _resolve_sub_team(request, team):
    """Resolve an optional `sub_team` from the request body.

    Returns `(sentinel_or_group, error_response)`. The first element is the
    module-level `_UNSET` when the key is absent (leave the current group
    alone), None when explicitly null (clear it), or a SubTeam.

    Setting a group is owner-only, so a manager PATCHing a role is refused the
    moment they include the key, rather than having it silently dropped.
    """
    if "sub_team" not in request.data:
        return _UNSET, None
    err = _require_owner(request, team)
    if err:
        return None, err
    raw = request.data.get("sub_team")
    if raw in (None, "", "null"):
        return None, None
    group = SubTeam.objects.filter(pk=raw, team=team).first()
    if group is None:
        return None, Response(
            {"detail": "That group belongs to a different team."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return group, None
```

And the sentinel, near `ROLE_LEVELS`:

```python
# Distinguishes "key absent" from an explicit null in a PATCH body.
_UNSET = object()
```

In `TeamMemberDetailView.patch`, after the owner-role guard and before `target.save(...)`:

```python
        new_group, group_err = _resolve_sub_team(request, team)
        if group_err:
            return group_err
```

Change the save and add the audit entry:

```python
        update_fields = ["role", "feature_access", "updated_at"]
        old_group_name = target.sub_team.name if target.sub_team_id else None
        if new_group is not _UNSET:
            target.sub_team = new_group
            update_fields.append("sub_team")
        target.save(update_fields=update_fields)
        if new_group is not _UNSET:
            AuditService.log(
                actor=request.user,
                action=ActivityLog.Action.TEAM_MEMBER_GROUP_CHANGED,
                team=team,
                description=(
                    f"Moved {target.user.email} from "
                    f"{old_group_name or 'no group'} to "
                    f"{new_group.name if new_group else 'no group'}"
                ),
                resource_type="team_membership", resource_id=str(target.pk),
                metadata={
                    "previous_group": old_group_name,
                    "new_group": new_group.name if new_group else None,
                },
            )
```

Leave the existing `TEAM_MEMBER_ROLE_CHANGED` log call where it is.

- [ ] **Step 7: Accept `sub_team` on create-user**

In `TeamCreateUserView.post`, right after the role validation block (`if ROLE_LEVELS[role] > my_level: ...`):

```python
        new_group, group_err = _resolve_sub_team(request, team)
        if group_err:
            return group_err
        group = None if new_group is _UNSET else new_group
```

Then pass it at both membership creation sites in that method. The existing-user branch:

```python
            membership = TeamMembership.objects.create(
                user=existing_user, team=team, role=role, sub_team=group
            )
```

Find the new-user branch's `TeamMembership.objects.create(...)` call further down the same method and add `sub_team=group` to it in the same way.

- [ ] **Step 8: Wire the URLs**

In `apps/accounts/urls.py`, add `SubTeamDetailView, SubTeamListCreateView` to the imports and these two routes next to the other team routes:

```python
    path("teams/<uuid:team_pk>/sub-teams/", SubTeamListCreateView.as_view(), name="sub-team-list-create"),
    path("teams/<uuid:team_pk>/sub-teams/<uuid:pk>/", SubTeamDetailView.as_view(), name="sub-team-detail"),
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `pytest tests/accounts/test_sub_teams_api.py -v --create-db`
Expected: 16 passed.

- [ ] **Step 10: Verify the whole accounts suite**

Run: `pytest tests/accounts -q --create-db`
Expected: all pass, including `test_custom_role.py` and `test_member_removal.py`, which exercise the same PATCH endpoint.

- [ ] **Step 11: Commit**

```bash
git add apps/audit/models.py apps/audit/migrations/0010_alter_activitylog_action.py apps/accounts/serializers.py apps/accounts/views.py apps/accounts/urls.py tests/accounts/test_sub_teams_api.py
git commit -m "feat(accounts): owner-only groups API and member group assignment"
```

---

### Task 6: Grants API

**Files:**
- Modify: `apps/credentials/serializers.py` (add two serializers)
- Modify: `apps/credentials/views.py` (add three views)
- Modify: `apps/credentials/urls.py`
- Create: `tests/credentials/test_group_grants_api.py`

**Interfaces:**
- Consumes: `SubTeamCredentialGrant` (Task 2), `_require_owner` pattern from Task 5 (re-implemented locally, see Step 3).
- Produces: url names `sub-team-grant-list-create`, `sub-team-grant-delete`, `credential-group-grants`.

- [ ] **Step 1: Write the failing tests**

Create `tests/credentials/test_group_grants_api.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamMembership
from apps.credentials.models import SubTeamCredentialGrant
from apps.credentials.services import CredentialService


def _client_for(user):
    c = APIClient()
    resp = c.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SecurePass1!"},
        format="json",
    )
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


@pytest.fixture
def group(db, team):
    return SubTeam.objects.create(team=team, name="Web Team")


@pytest.fixture
def manager(db, django_user_model, team):
    u = django_user_model.objects.create_user(email="mgr2@x.io", password="SecurePass1!")
    TeamMembership.objects.create(user=u, team=team, role=TeamMembership.Role.MANAGER)
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u


@pytest.fixture
def credential(db, team):
    return CredentialService.create(
        team=team, website=None, label="cPanel", credential_type="cpanel",
        login_url="", username="u", password="p", notes="", created_by=None,
    )


def test_owner_creates_a_blanket_grant(auth_client, group):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "all"}, format="json",
    )
    assert resp.status_code == 201
    assert resp.data["scope"] == "all"
    assert resp.data["can_view_password"] is False


def test_reveal_must_be_asked_for_explicitly(auth_client, group):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "all", "can_view_password": True}, format="json",
    )
    assert resp.data["can_view_password"] is True


def test_owner_creates_a_type_grant(auth_client, group):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "type", "credential_type": "cpanel"}, format="json",
    )
    assert resp.status_code == 201
    assert resp.data["credential_type"] == "cpanel"


def test_type_grant_rejects_an_unknown_credential_type(auth_client, group):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "type", "credential_type": "not_a_type"}, format="json",
    )
    assert resp.status_code == 400


def test_owner_creates_a_single_credential_grant(auth_client, group, credential):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "credential", "credential": str(credential.pk)}, format="json",
    )
    assert resp.status_code == 201
    assert resp.data["credential_label"] == "cPanel"


def test_blanket_grant_rejects_a_target(auth_client, group, credential):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "all", "credential": str(credential.pk)}, format="json",
    )
    assert resp.status_code == 400


def test_duplicate_blanket_grant_is_rejected(auth_client, group):
    auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/", {"scope": "all"}, format="json",
    )
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/", {"scope": "all"}, format="json",
    )
    assert resp.status_code == 400


def test_manager_cannot_create_a_grant(manager, group):
    resp = _client_for(manager).post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/", {"scope": "all"}, format="json",
    )
    assert resp.status_code == 403


def test_manager_cannot_list_grants(manager, group):
    resp = _client_for(manager).get(f"/api/v1/sub-teams/{group.pk}/credential-grants/")
    assert resp.status_code == 403


def test_owner_lists_grants(auth_client, group):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    resp = auth_client.get(f"/api/v1/sub-teams/{group.pk}/credential-grants/")
    assert resp.status_code == 200
    assert len(resp.data) == 1


def test_owner_revokes_a_grant(auth_client, group):
    grant = SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    resp = auth_client.delete(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/{grant.pk}/"
    )
    assert resp.status_code == 204
    assert not SubTeamCredentialGrant.objects.exists()


def test_manager_cannot_revoke_a_grant(manager, group):
    grant = SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    resp = _client_for(manager).delete(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/{grant.pk}/"
    )
    assert resp.status_code == 403
    assert SubTeamCredentialGrant.objects.exists()


def test_a_group_in_another_team_is_not_reachable(auth_client, django_user_model):
    from apps.accounts.services import TeamService

    other_owner = django_user_model.objects.create_user(email="oy@x.io", password="x")
    other = TeamService.create(name="Other", owner=other_owner)
    foreign = SubTeam.objects.create(team=other, name="Web Team")
    resp = auth_client.post(
        f"/api/v1/sub-teams/{foreign.pk}/credential-grants/", {"scope": "all"}, format="json",
    )
    assert resp.status_code == 404


def test_credential_grant_from_another_team_is_rejected(auth_client, group, django_user_model):
    from apps.accounts.services import TeamService

    other_owner = django_user_model.objects.create_user(email="oz@x.io", password="x")
    other = TeamService.create(name="Other", owner=other_owner)
    foreign = CredentialService.create(
        team=other, website=None, label="F", credential_type="cpanel",
        login_url="", username="u", password="p", notes="", created_by=None,
    )
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "credential", "credential": str(foreign.pk)}, format="json",
    )
    assert resp.status_code == 400


def test_per_credential_grants_are_listed_for_one_credential(auth_client, group, credential):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL, credential=credential,
    )
    resp = auth_client.get(f"/api/v1/credentials/{credential.pk}/group-grants/")
    assert resp.status_code == 200
    assert resp.data[0]["sub_team_name"] == "Web Team"


def test_shares_endpoint_still_returns_a_bare_array(auth_client, credential):
    """Response shape is load-bearing: the deployed frontend expects a list."""
    resp = auth_client.get(f"/api/v1/credentials/{credential.pk}/shares/")
    assert resp.status_code == 200
    assert isinstance(resp.data, list)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/credentials/test_group_grants_api.py -v --create-db`
Expected: FAIL with 404s, except the last test which already passes and must keep passing.

- [ ] **Step 3: Add the serializers**

In `apps/credentials/serializers.py`:

```python
class SubTeamCredentialGrantSerializer(BaseModelSerializer):
    """Read shape for a group grant."""

    sub_team_name = serializers.CharField(source="sub_team.name", read_only=True)
    credential_label = serializers.SerializerMethodField()
    granted_by_email = serializers.SerializerMethodField()

    class Meta:
        model = SubTeamCredentialGrant
        fields = (
            "id", "sub_team", "sub_team_name", "scope", "credential_type",
            "credential", "credential_label", "can_view_password",
            "granted_by_email", "created_at",
        )
        read_only_fields = fields

    def get_credential_label(self, obj) -> str | None:
        return obj.credential.label if obj.credential_id else None

    def get_granted_by_email(self, obj) -> str | None:
        return obj.granted_by.email if obj.granted_by_id else None


class SubTeamCredentialGrantWriteSerializer(serializers.Serializer):
    """Write shape. Mirrors the model's clean() because DRF never calls it.

    can_view_password defaults to False: a grant is use-only until the owner
    deliberately widens it.
    """

    scope = serializers.ChoiceField(choices=SubTeamCredentialGrant.Scope.choices)
    credential_type = serializers.ChoiceField(
        choices=Credential.CredentialType.choices, required=False, allow_blank=True,
    )
    credential = serializers.UUIDField(required=False, allow_null=True)
    can_view_password = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        scope = attrs["scope"]
        cred_type = attrs.get("credential_type") or ""
        credential = attrs.get("credential")
        if scope == SubTeamCredentialGrant.Scope.ALL:
            if cred_type or credential:
                raise serializers.ValidationError(
                    "A grant covering all credentials takes no target."
                )
        elif scope == SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE:
            if not cred_type:
                raise serializers.ValidationError(
                    {"credential_type": "Required for a credential-type grant."}
                )
            if credential:
                raise serializers.ValidationError(
                    {"credential": "Not allowed on a credential-type grant."}
                )
        else:
            if not credential:
                raise serializers.ValidationError(
                    {"credential": "Required for a single-credential grant."}
                )
            if cred_type:
                raise serializers.ValidationError(
                    {"credential_type": "Not allowed on a single-credential grant."}
                )
        return attrs
```

Import `SubTeamCredentialGrant` and `Credential` at the top of that module as needed.

- [ ] **Step 4: Add the views**

In `apps/credentials/views.py`:

```python
def _owner_group_or_error(request, sub_team_pk):
    """Resolve a SubTeam the caller owns.

    Returns `(group, None)` or `(None, Response)`. A group in another team is a
    404 rather than a 403: the caller has no business knowing it exists.
    Grants are owner-only to read as well as write, because the grant list is
    the access-control policy itself.
    """
    from apps.accounts.models import SubTeam, TeamMembership

    team = request.user.active_team
    if team is None:
        return None, Response(status=status.HTTP_404_NOT_FOUND)
    group = SubTeam.objects.filter(pk=sub_team_pk, team=team).first()
    if group is None:
        return None, Response(status=status.HTTP_404_NOT_FOUND)
    is_owner = TeamMembership.objects.filter(
        user=request.user, team=team, role=TeamMembership.Role.OWNER
    ).exists()
    if not is_owner:
        return None, Response(
            {"detail": "Team owner required."}, status=status.HTTP_403_FORBIDDEN
        )
    return group, None


class SubTeamGrantListCreateView(APIView):
    """GET/POST /api/v1/sub-teams/<sub_team_pk>/credential-grants/ — owner only."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, sub_team_pk):
        group, err = _owner_group_or_error(request, sub_team_pk)
        if err:
            return err
        grants = group.credential_grants.select_related("credential", "granted_by", "sub_team")
        return Response(SubTeamCredentialGrantSerializer(grants, many=True).data)

    def post(self, request, sub_team_pk):
        group, err = _owner_group_or_error(request, sub_team_pk)
        if err:
            return err

        ser = SubTeamCredentialGrantWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        credential = None
        if data["scope"] == SubTeamCredentialGrant.Scope.CREDENTIAL:
            # Scoped to the group's own team, so a foreign credential is a 400
            # rather than a silent cross-tenant grant.
            credential = Credential.objects.filter(
                pk=data["credential"], team=group.team
            ).first()
            if credential is None:
                return Response(
                    {"detail": "That credential belongs to a different team."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        grant = SubTeamCredentialGrant(
            sub_team=group,
            scope=data["scope"],
            credential_type=data.get("credential_type") or "",
            credential=credential,
            can_view_password=data.get("can_view_password", False),
            granted_by=request.user,
        )
        try:
            grant.full_clean(exclude=["granted_by"])
            grant.save()
        except DjangoValidationError as exc:
            return Response(
                {"detail": "; ".join(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except IntegrityError:
            return Response(
                {"detail": "That group already has this grant."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_GROUP_GRANTED,
            description=(
                f"Granted group '{group.name}' access to "
                f"{grant.credential.label if grant.credential_id else grant.get_scope_display().lower()}"
            ),
            resource_type="sub_team_credential_grant", resource_id=grant.pk,
            metadata={
                "sub_team_id": str(group.pk),
                "scope": grant.scope,
                "credential_type": grant.credential_type,
                "credential_id": str(grant.credential_id) if grant.credential_id else None,
                "can_view_password": grant.can_view_password,
            },
        )
        return Response(
            SubTeamCredentialGrantSerializer(grant).data,
            status=status.HTTP_201_CREATED,
        )


class SubTeamGrantDeleteView(APIView):
    """DELETE /api/v1/sub-teams/<sub_team_pk>/credential-grants/<pk>/ — owner only."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def delete(self, request, sub_team_pk, pk):
        group, err = _owner_group_or_error(request, sub_team_pk)
        if err:
            return err
        grant = group.credential_grants.filter(pk=pk).first()
        if grant is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        label = grant.credential.label if grant.credential_id else grant.get_scope_display().lower()
        grant.delete()
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_GROUP_REVOKED,
            description=f"Revoked group '{group.name}' access to {label}",
            resource_type="sub_team_credential_grant", resource_id=pk,
            metadata={"sub_team_id": str(group.pk)},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class CredentialGroupGrantListView(APIView):
    """GET /api/v1/credentials/<pk>/group-grants/ — owner only.

    The grants that reach one specific credential, so the share dialog can show
    group access next to user access. Read-only: grants are created through the
    sub-team collection. The shares endpoint keeps its bare-array response
    shape, because the deployed frontend depends on it.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, pk):
        from apps.accounts.models import TeamMembership

        team = request.user.active_team
        if team is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not TeamMembership.objects.filter(
            user=request.user, team=team, role=TeamMembership.Role.OWNER
        ).exists():
            return Response(
                {"detail": "Team owner required."}, status=status.HTTP_403_FORBIDDEN
            )
        credential = Credential.objects.filter(pk=pk, team=team).first()
        if credential is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        grants = SubTeamCredentialGrant.objects.filter(
            sub_team__team=team
        ).filter(
            Q(scope=SubTeamCredentialGrant.Scope.ALL)
            | Q(
                scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE,
                credential_type=credential.credential_type,
            )
            | Q(scope=SubTeamCredentialGrant.Scope.CREDENTIAL, credential=credential)
        ).select_related("sub_team", "credential", "granted_by")
        return Response(SubTeamCredentialGrantSerializer(grants, many=True).data)
```

Add these imports at the top of `apps/credentials/views.py`:

```python
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.db.utils import IntegrityError

from apps.credentials.models import SubTeamCredentialGrant
from apps.credentials.serializers import (
    SubTeamCredentialGrantSerializer,
    SubTeamCredentialGrantWriteSerializer,
)
```

Check whether `Q` is already imported at module level in that file; it is currently imported inside `ExtensionCredentialLookupView.get_queryset`. Hoist it to the top and delete the local import.

- [ ] **Step 5: Wire the URLs**

In `apps/credentials/urls.py`, add the three view imports and:

```python
    path(
        "sub-teams/<uuid:sub_team_pk>/credential-grants/",
        SubTeamGrantListCreateView.as_view(),
        name="sub-team-grant-list-create",
    ),
    path(
        "sub-teams/<uuid:sub_team_pk>/credential-grants/<uuid:pk>/",
        SubTeamGrantDeleteView.as_view(),
        name="sub-team-grant-delete",
    ),
    path(
        "credentials/<uuid:pk>/group-grants/",
        CredentialGroupGrantListView.as_view(),
        name="credential-group-grants",
    ),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/credentials/test_group_grants_api.py -v --create-db`
Expected: 16 passed.

- [ ] **Step 7: Run the full backend suite**

Run: `pytest -q --create-db`
Expected: all pass. This is the gate before any frontend work starts.

- [ ] **Step 8: Commit**

```bash
git add apps/credentials/serializers.py apps/credentials/views.py apps/credentials/urls.py tests/credentials/test_group_grants_api.py
git commit -m "feat(credentials): owner-only group credential grants API"
```

---

### Task 7: Frontend groups management on the team page

**Files:**
- Modify: `frontend/src/lib/api.ts` (types)
- Create: `frontend/src/app/api/teams/[id]/sub-teams/route.ts`
- Create: `frontend/src/app/api/teams/[id]/sub-teams/[groupId]/route.ts`
- Modify: `frontend/src/app/(dashboard)/team/page.tsx`
- Modify: `frontend/src/components/team-management-client.tsx`
- Create: `frontend/src/components/team-groups-panel.tsx`

**Interfaces:**
- Consumes: the Task 5 endpoints.
- Produces: `SubTeam` type `{ id: string; name: string; description?: string; member_count?: number }`; `TeamGroupsPanel` component with props `{ teamId: string; isOwner: boolean; initialGroups: SubTeam[] }`.

- [ ] **Step 1: Read the Next.js 16 route handler guide**

Read `frontend/node_modules/next/dist/docs/` for the App Router route handler and dynamic-params conventions. Next.js 16 differs from older patterns, notably that `params` is a Promise that must be awaited. Copy the exact shape used by the existing `frontend/src/app/api/teams/[id]/members/[memberId]/route.ts` rather than writing it from memory.

- [ ] **Step 2: Add the types**

In `frontend/src/lib/api.ts`:

```typescript
export interface SubTeam {
  id: string;
  name: string;
  description?: string;
  member_count?: number;
  created_at?: string;
}
```

Extend the existing `TeamMember` interface with optional fields, so a frontend deployed ahead of the backend still renders:

```typescript
  sub_team?: string | null;
  sub_team_name?: string | null;
```

- [ ] **Step 3: Add the proxy routes**

Create `frontend/src/app/api/teams/[id]/sub-teams/route.ts` handling GET and POST, and `.../[groupId]/route.ts` handling PATCH and DELETE. Mirror `frontend/src/app/api/teams/[id]/members/route.ts` exactly: same token read, same `api.get`/`api.post` call, same error passthrough. Target `/api/v1/auth/teams/${id}/sub-teams/` and `/api/v1/auth/teams/${id}/sub-teams/${groupId}/`.

- [ ] **Step 4: Fetch groups on the team page**

In `frontend/src/app/(dashboard)/team/page.tsx`, add a third promise to the inner `Promise.allSettled` (the one already fetching members and reset requests):

```typescript
        api.get<SubTeam[]>(`/api/v1/auth/teams/${activeTeam.id}/sub-teams/`, token),
```

Follow the existing pattern for unwrapping: `groups = groupsResult.status === "fulfilled" && Array.isArray(groupsResult.value) ? groupsResult.value : []`. Return `groups` from `getData` and pass `initialGroups={groups}` to `TeamManagementClient`.

- [ ] **Step 5: Build the groups panel**

Create `frontend/src/components/team-groups-panel.tsx`. A client component that renders the group list with member counts, and for an owner adds a create form and per-row rename and delete. Requirements:

- The delete confirmation must name the consequence: `` `Delete "${g.name}"? ${g.member_count ?? 0} member(s) will be left with no group and will lose any access that group granted.` ``
- No em dashes or en dashes in any visible string.
- Non-owners see the list read-only, with no create form and no row actions.
- On any mutation, call `router.refresh()` (already the pattern in `team-management-client.tsx`) rather than hand-rolling local state sync.

- [ ] **Step 6: Mount the panel and add the group select**

In `frontend/src/components/team-management-client.tsx`:

- Add `initialGroups: SubTeam[]` to the props interface and render `<TeamGroupsPanel teamId={teamId} isOwner={myRole === "owner"} initialGroups={initialGroups} />` above the member list.
- Add `sub_team: ""` to the `addForm` state at line ~133 and to the two `setAddForm({...})` resets.
- In the add-member form, next to the existing Role `Select` (~line 343), add a Group `Select`, rendered only when `myRole === "owner"` and `initialGroups.length > 0`. Include an explicit "No group" option whose value maps to omitting the key. Label it `Group`, with helper text `Controls which credentials this person can see.`
- In `handleAddMember`, include `sub_team` in the POST body **only** when it is a non-empty string. Sending `sub_team: ""` would make the backend reject a manager's own create-user call, because `_resolve_sub_team` refuses any request that carries the key.
- On each member row, render `{m.sub_team_name ?? "No group"}` as a small badge. For an owner, make it a `Select` that PATCHes `{ role: m.role, sub_team: value || null }` to the existing member endpoint. The `role` key is required: that endpoint validates it on every PATCH.

- [ ] **Step 7: Verify the build and lint**

Run: `cd frontend && npm run lint && npm run build`
Expected: no errors. A TypeScript error about `params` being a Promise means Step 1 was skipped.

- [ ] **Step 8: Manual check**

Run the backend and `npm run dev`, then as the owner: create "Web Team", add a member into it, confirm the badge, rename the group, move the member to a second group, delete a group and confirm the member reads "No group". Log in as a manager and confirm the create form and row actions are absent.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/app/api/teams frontend/src/app/\(dashboard\)/team/page.tsx frontend/src/components/team-management-client.tsx frontend/src/components/team-groups-panel.tsx
git commit -m "feat(frontend): manage credential groups and assign members"
```

---

### Task 8: Frontend group access for credentials

**Files:**
- Modify: `frontend/src/lib/api.ts` (grant type)
- Create: `frontend/src/app/api/sub-teams/[groupId]/credential-grants/route.ts`
- Create: `frontend/src/app/api/sub-teams/[groupId]/credential-grants/[grantId]/route.ts`
- Create: `frontend/src/app/api/credentials/[id]/group-grants/route.ts`
- Modify: `frontend/src/app/(dashboard)/credentials/page.tsx` and its client components
- Create: `frontend/src/components/credential-group-access-panel.tsx`

**Interfaces:**
- Consumes: the Task 6 endpoints.
- Produces: `CredentialGroupGrant` type `{ id: string; sub_team: string; sub_team_name?: string; scope: "all" | "type" | "credential"; credential_type?: string; credential?: string | null; credential_label?: string | null; can_view_password: boolean }`.

- [ ] **Step 1: Add the type**

In `frontend/src/lib/api.ts`:

```typescript
export interface CredentialGroupGrant {
  id: string;
  sub_team: string;
  sub_team_name?: string;
  scope: "all" | "type" | "credential";
  credential_type?: string;
  credential?: string | null;
  credential_label?: string | null;
  can_view_password: boolean;
  granted_by_email?: string | null;
  created_at?: string;
}
```

- [ ] **Step 2: Add the three proxy routes**

Mirror `frontend/src/app/api/credentials/[id]/shares/route.ts` for shape. Targets: `/api/v1/sub-teams/${groupId}/credential-grants/` (GET, POST), `/api/v1/sub-teams/${groupId}/credential-grants/${grantId}/` (DELETE), `/api/v1/credentials/${id}/group-grants/` (GET).

- [ ] **Step 3: Build the group access panel**

Create `frontend/src/components/credential-group-access-panel.tsx`, an owner-only client component for the blanket rules. It renders one section per group, each listing that group's grants with a revoke button, plus a form to add one: a scope radio (All credentials / By credential type / and nothing else, since single-credential grants belong in the share dialog), a credential-type select when scope is `type`, and a "Allow this group to see passwords" checkbox defaulting to unchecked.

Helper text under the checkbox, worded to match what the backend actually enforces, and with no dashes:

```
Off means the group can autofill logins with the extension but the password is
never shown in the dashboard. Every autofill use is logged against the person
who used it.
```

Do not write copy claiming the password cannot be obtained. It can, and the spec says so.

- [ ] **Step 4: Mount the panel on the credentials page**

Render the panel on `frontend/src/app/(dashboard)/credentials/page.tsx` behind an owner check, fetching the team's groups server-side the same way the team page does. Non-owners must not see it at all, since the grants endpoint 403s for them and a visible-but-broken panel is worse than none.

- [ ] **Step 5: Add group rows to the share dialog**

In the credential share dialog component (the one calling `/api/credentials/[id]/shares`), add a Groups section for owners that reads `GET /api/credentials/[id]/group-grants/` and lists each grant as `sub_team_name` plus a plain-language reason: "all credentials", "all cPanel credentials", or "this credential". A grant whose scope is `credential` gets a revoke button; blanket grants get a note saying they are managed in Group access, since revoking one from here would silently remove a rule affecting the whole vault.

- [ ] **Step 6: Verify the build and lint**

Run: `cd frontend && npm run lint && npm run build`
Expected: no errors.

- [ ] **Step 7: End-to-end manual check**

As the owner: give Web Team a blanket grant with reveal off. Log in as a Web Team developer and confirm every credential is listed, and that revealing one shows the username with the password hidden. Load a client site with the extension signed in as that developer and confirm autofill still fills the password. Check the credential's access log shows an `autofill` entry. Then turn reveal on for the group and confirm the dashboard now shows the password.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/app/api/sub-teams frontend/src/app/api/credentials frontend/src/app/\(dashboard\)/credentials frontend/src/components/credential-group-access-panel.tsx
git commit -m "feat(frontend): grant credential groups access from the vault"
```

---

## Verification before calling this done

- [ ] `pytest -q --create-db` passes in full.
- [ ] `cd frontend && npm run lint && npm run build` passes.
- [ ] `git grep -n "for_autofill" apps/credentials/views.py` returns nothing. The dashboard endpoint must not read that flag.
- [ ] `git grep -n "else True" apps/credentials/services.py` returns nothing in `can_view_password`.
- [ ] A manager receives 403 from every group and grant write, verified by the tests in Tasks 5 and 6.
- [ ] No em dashes or en dashes in new user-facing strings: `git grep -nP "[\x{2013}\x{2014}]" frontend/src/components/team-groups-panel.tsx frontend/src/components/credential-group-access-panel.tsx` returns nothing.
