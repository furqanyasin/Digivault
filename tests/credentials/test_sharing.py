"""Tests for credential share endpoints.

POST   /api/v1/credentials/<pk>/shares/   — share with developers
GET    /api/v1/credentials/<pk>/shares/   — list shares
DELETE /api/v1/credentials/<pk>/shares/<user_id>/  — revoke
"""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership
from apps.audit.models import ActivityLog
from apps.credentials.models import Credential, CredentialShare
from apps.credentials.services import CredentialService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def team(db, django_user_model):
    from apps.accounts.services import TeamService
    owner = django_user_model.objects.create_user(
        email="share_owner@x.io", password="Pass123!"
    )
    return TeamService.create(name="ShareCo", owner=owner)


@pytest.fixture
def make_user(db, django_user_model):
    def _make(email, team, role):
        u = django_user_model.objects.create_user(email=email, password="Pass123!")
        TeamMembership.objects.create(user=u, team=team, role=role)
        u.active_team = team
        u.save(update_fields=["active_team"])
        return u
    return _make


@pytest.fixture
def owner_user(team):
    # The team owner was created inside TeamService; retrieve via membership
    return TeamMembership.objects.get(
        team=team, role=TeamMembership.Role.OWNER
    ).user


@pytest.fixture
def dev1(team, make_user):
    """Developer who is also the credential creator."""
    return make_user("dev1@x.io", team, TeamMembership.Role.DEVELOPER)


@pytest.fixture
def dev2(team, make_user):
    return make_user("dev2@x.io", team, TeamMembership.Role.DEVELOPER)


@pytest.fixture
def dev3(team, make_user):
    return make_user("dev3@x.io", team, TeamMembership.Role.DEVELOPER)


@pytest.fixture
def manager(team, make_user):
    return make_user("mgr@x.io", team, TeamMembership.Role.MANAGER)


@pytest.fixture
def cred(team, dev1):
    """A credential created by dev1."""
    return CredentialService.create(
        team=team,
        website=None,
        label="DB Creds",
        credential_type="custom",
        login_url="",
        username="dbuser",
        password="dbpass",
        notes="",
        created_by=dev1,
    )


def _client_for(user):
    """Return an authenticated APIClient for *user* using JWT."""
    c = APIClient()
    resp = c.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "Pass123!"},
        format="json",
    )
    assert resp.status_code == 200, f"Token request failed for {user.email}: {resp.data}"
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_owner_can_share(owner_user, dev2, cred):
    client = _client_for(owner_user)
    resp = client.post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(dev2.pk)]},
        format="json",
    )
    assert resp.status_code == 201
    assert CredentialShare.objects.filter(credential=cred, user=dev2).exists()
    assert ActivityLog.objects.filter(
        action=ActivityLog.Action.CREDENTIAL_SHARED,
        resource_id=str(cred.pk),
    ).exists()


@pytest.mark.django_db
def test_manager_can_share(manager, dev2, cred):
    client = _client_for(manager)
    resp = client.post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(dev2.pk)]},
        format="json",
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_creator_can_share(dev1, dev2, cred):
    """dev1 is the credential creator — should be able to share with dev2."""
    client = _client_for(dev1)
    resp = client.post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(dev2.pk)]},
        format="json",
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_shared_dev_cannot_share(owner_user, dev2, dev3, cred):
    """dev2 only has a share (not creator/owner/manager) — cannot share dev3."""
    # First share cred with dev2
    CredentialShare.objects.create(credential=cred, user=dev2, shared_by=owner_user)

    client = _client_for(dev2)
    resp = client.post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(dev3.pk)]},
        format="json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_unrelated_dev_cannot_see(dev2, cred):
    """dev2 has no share — GET credential detail should return 404."""
    client = _client_for(dev2)
    resp = client.get(f"/api/v1/credentials/{cred.pk}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_shared_dev_can_view_and_reveal(owner_user, dev2, cred):
    """dev2 with an active share can GET the detail and POST reveal."""
    CredentialShare.objects.create(credential=cred, user=dev2, shared_by=owner_user)

    client = _client_for(dev2)
    detail_resp = client.get(f"/api/v1/credentials/{cred.pk}/")
    assert detail_resp.status_code == 200

    reveal_resp = client.post(f"/api/v1/credentials/{cred.pk}/reveal/")
    assert reveal_resp.status_code == 200


@pytest.mark.django_db
def test_shared_dev_cannot_edit_or_delete(owner_user, dev2, cred):
    """dev2 with a share cannot PATCH or DELETE the credential."""
    CredentialShare.objects.create(credential=cred, user=dev2, shared_by=owner_user)

    client = _client_for(dev2)
    patch_resp = client.patch(
        f"/api/v1/credentials/{cred.pk}/",
        {"label": "hacked"},
        format="json",
    )
    assert patch_resp.status_code == 403

    delete_resp = client.delete(f"/api/v1/credentials/{cred.pk}/")
    assert delete_resp.status_code == 403


@pytest.mark.django_db
def test_share_with_manager_is_noop(owner_user, manager, cred):
    """Sharing with a manager is a no-op: 200 returned, no CredentialShare row."""
    client = _client_for(owner_user)
    resp = client.post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(manager.pk)]},
        format="json",
    )
    # Manager was filtered out (not a developer) — no new share rows created → 200
    assert resp.status_code == 200
    assert not CredentialShare.objects.filter(credential=cred, user=manager).exists()


@pytest.mark.django_db
def test_share_with_non_team_member_is_400(owner_user, cred, db, django_user_model):
    """Sharing with a user outside the team should return 400."""
    outsider = django_user_model.objects.create_user(
        email="outsider@other.io", password="Pass123!"
    )
    client = _client_for(owner_user)
    resp = client.post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(outsider.pk)]},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_unshare_revokes_access(owner_user, dev2, cred):
    """Deleting a share revokes dev2's access and logs CREDENTIAL_UNSHARED."""
    CredentialShare.objects.create(credential=cred, user=dev2, shared_by=owner_user)

    client = _client_for(owner_user)
    del_resp = client.delete(
        f"/api/v1/credentials/{cred.pk}/shares/{dev2.pk}/"
    )
    assert del_resp.status_code == 204

    # dev2 can no longer see the credential
    dev2_client = _client_for(dev2)
    get_resp = dev2_client.get(f"/api/v1/credentials/{cred.pk}/")
    assert get_resp.status_code == 404

    assert ActivityLog.objects.filter(
        action=ActivityLog.Action.CREDENTIAL_UNSHARED,
        resource_id=str(cred.pk),
    ).exists()


@pytest.mark.django_db
def test_share_list_returns_current_shares(owner_user, dev2, cred):
    """GET /shares/ returns the current shares including dev2's email and shared_by_email."""
    # Set active_team on owner_user so it can authenticate properly
    CredentialShare.objects.create(credential=cred, user=dev2, shared_by=owner_user)

    client = _client_for(owner_user)
    resp = client.get(f"/api/v1/credentials/{cred.pk}/shares/")
    assert resp.status_code == 200

    # Handle both enveloped and non-enveloped response
    body = resp.json()
    rows = body["data"] if isinstance(body, dict) and "data" in body else body

    assert len(rows) >= 1
    emails = [r["email"] for r in rows]
    assert dev2.email in emails

    shared_by_emails = [r.get("shared_by_email") for r in rows if r["email"] == dev2.email]
    assert owner_user.email in shared_by_emails


# ---------------------------------------------------------------------------
# can_view_password flag + reveal enforcement
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_share_without_password_hides_it_on_reveal(owner_user, dev2, cred):
    """A share with can_view_password=False blanks the password on dashboard reveal."""
    client = _client_for(owner_user)
    resp = client.post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(dev2.pk)], "can_view_password": False},
        format="json",
    )
    assert resp.status_code == 201
    assert CredentialShare.objects.get(credential=cred, user=dev2).can_view_password is False

    dev2_client = _client_for(dev2)
    reveal = dev2_client.post(f"/api/v1/credentials/{cred.pk}/reveal/")
    assert reveal.status_code == 200
    assert reveal.data["password"] == ""
    assert reveal.data["password_hidden"] is True
    # Username/notes still come through.
    assert reveal.data["username"] == "dbuser"


@pytest.mark.django_db
def test_autofill_still_returns_password_when_hidden(owner_user, dev2, cred):
    """for_autofill bypasses the hide so the extension can fill the form."""
    CredentialShare.objects.create(
        credential=cred, user=dev2, shared_by=owner_user, can_view_password=False
    )
    dev2_client = _client_for(dev2)
    reveal = dev2_client.post(f"/api/v1/credentials/{cred.pk}/reveal/?for_autofill=1")
    assert reveal.status_code == 200
    assert reveal.data["password"] == "dbpass"
    assert reveal.data["password_hidden"] is False


@pytest.mark.django_db
def test_owner_always_sees_password(owner_user, cred):
    """Owners are never subject to can_view_password restrictions."""
    client = _client_for(owner_user)
    reveal = client.post(f"/api/v1/credentials/{cred.pk}/reveal/")
    assert reveal.data["password"] == "dbpass"
    assert reveal.data["password_hidden"] is False


@pytest.mark.django_db
def test_resharing_updates_flag_without_duplicate(owner_user, dev2, cred):
    """Re-sharing the same credential updates the flag in place."""
    client = _client_for(owner_user)
    client.post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(dev2.pk)], "can_view_password": True},
        format="json",
    )
    client.post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(dev2.pk)], "can_view_password": False},
        format="json",
    )
    shares = CredentialShare.objects.filter(credential=cred, user=dev2)
    assert shares.count() == 1
    assert shares.first().can_view_password is False


# ---------------------------------------------------------------------------
# Site-level sharing
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_site_level_share_covers_all_credentials(owner_user, dev2, team):
    """Sharing a website shares every one of its credentials at once."""
    from apps.websites.models import Website

    site = Website.objects.create(team=team, name="Site", domain="site.io")
    c1 = CredentialService.create(
        team=team, website=site, label="A", credential_type="custom",
        login_url="", username="a", password="p", notes="", created_by=owner_user,
    )
    c2 = CredentialService.create(
        team=team, website=site, label="B", credential_type="custom",
        login_url="", username="b", password="p", notes="", created_by=owner_user,
    )

    client = _client_for(owner_user)
    resp = client.post(
        f"/api/v1/websites/{site.pk}/credentials/share/",
        {"user_ids": [str(dev2.pk)], "can_view_password": False},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["shared_credentials"] == 2
    for c in (c1, c2):
        share = CredentialShare.objects.get(credential=c, user=dev2)
        assert share.can_view_password is False
