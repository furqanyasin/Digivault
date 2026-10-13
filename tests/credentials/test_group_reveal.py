import pytest
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamMembership
from apps.credentials.models import (
    CredentialAccessLog,
    CredentialShare,
    SubTeamCredentialGrant,
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
