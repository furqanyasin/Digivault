"""Secure user onboarding + first-login hardening."""

import pytest

from apps.accounts.models import PasswordResetRequest, TeamMembership, User


def _make_member(team, *, must_change, totp_enabled=False, password="TempPass1!"):
    u = User.objects.create_user(email="newbie@example.com", password=password)
    u.must_change_password = must_change
    u.totp_enabled = totp_enabled
    u.save(update_fields=["must_change_password", "totp_enabled"])
    TeamMembership.objects.create(user=u, team=team, role=TeamMembership.Role.DEVELOPER)
    return u


@pytest.mark.django_db
def test_me_includes_must_change_password(auth_client):
    resp = auth_client.get("/api/v1/auth/me/")
    assert resp.status_code == 200
    assert "must_change_password" in resp.data
    assert resp.data["must_change_password"] is False


@pytest.mark.django_db
def test_login_requires_password_change_when_flagged(api_client, team):
    _make_member(team, must_change=True)
    resp = api_client.post(
        "/api/v1/auth/login/",
        {"email": "newbie@example.com", "password": "TempPass1!"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data.get("requires_password_change") is True
    assert resp.data.get("session_key")


@pytest.mark.django_db
def test_password_change_takes_priority_over_2fa_setup(api_client, team):
    _make_member(team, must_change=True, totp_enabled=False)
    resp = api_client.post(
        "/api/v1/auth/login/",
        {"email": "newbie@example.com", "password": "TempPass1!"},
        format="json",
    )
    assert resp.data.get("requires_password_change") is True
    assert "requires_setup" not in resp.data


@pytest.mark.django_db
def test_first_password_sets_and_clears_flag(api_client, team):
    _make_member(team, must_change=True)
    login = api_client.post(
        "/api/v1/auth/login/",
        {"email": "newbie@example.com", "password": "TempPass1!"},
        format="json",
    )
    session_key = login.data["session_key"]

    resp = api_client.post(
        "/api/v1/auth/first-password/",
        {"session_key": session_key, "password": "BrandNewPass9!"},
        format="json",
    )
    assert resp.status_code == 200

    u = User.objects.get(email="newbie@example.com")
    assert u.must_change_password is False
    assert u.check_password("BrandNewPass9!")


@pytest.mark.django_db
def test_first_password_rejects_expired_session(api_client):
    resp = api_client.post(
        "/api/v1/auth/first-password/",
        {"session_key": "deadbeef", "password": "BrandNewPass9!"},
        format="json",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_first_password_rejects_weak_password(api_client, team):
    _make_member(team, must_change=True)
    login = api_client.post(
        "/api/v1/auth/login/",
        {"email": "newbie@example.com", "password": "TempPass1!"},
        format="json",
    )
    resp = api_client.post(
        "/api/v1/auth/first-password/",
        {"session_key": login.data["session_key"], "password": "123"},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_create_user_blank_password_emails_set_password_link(auth_client, team):
    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.id}/users/",
        {"name": "Pat Doe", "email": "pat@example.com", "role": "developer"},
        format="json",
    )
    assert resp.status_code == 201
    u = User.objects.get(email="pat@example.com")
    assert not u.has_usable_password()
    assert u.must_change_password is False
    pr = PasswordResetRequest.objects.get(user=u)
    assert pr.status == PasswordResetRequest.Status.APPROVED
    assert pr.reset_token
    # The set-password link is returned to the admin so onboarding never depends
    # on email delivery (SMTP may be unconfigured/down).
    assert pr.reset_token in resp.data["set_password_url"]
    assert "email_sent" in resp.data


@pytest.mark.django_db
def test_create_user_with_password_sets_must_change(auth_client, team):
    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.id}/users/",
        {"name": "Sam Roe", "email": "sam@example.com", "role": "developer", "password": "AdminSet123!"},
        format="json",
    )
    assert resp.status_code == 201
    u = User.objects.get(email="sam@example.com")
    assert u.must_change_password is True
    assert u.check_password("AdminSet123!")
    assert not PasswordResetRequest.objects.filter(user=u).exists()


@pytest.mark.django_db
def test_re_add_existing_unonboarded_user_reissues_set_password_link(auth_client, team):
    # A user that exists but never finished onboarding (no usable password),
    # e.g. invited earlier while SMTP was down and later removed from the team.
    stale = User.objects.create_user(email="stale@example.com", password=None)
    stale.set_unusable_password()
    stale.save(update_fields=["password"])

    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.id}/users/",
        {"name": "Stale User", "email": "stale@example.com", "role": "developer"},
        format="json",
    )
    assert resp.status_code == 201
    # A fresh set-password link is issued and returned so they can finally log in.
    pr = PasswordResetRequest.objects.filter(user=stale).latest("created_at")
    assert pr.status == PasswordResetRequest.Status.APPROVED
    assert pr.reset_token in resp.data["set_password_url"]
    assert "email_sent" in resp.data
    assert TeamMembership.objects.filter(user=stale, team=team).exists()


@pytest.mark.django_db
def test_re_add_existing_active_user_sends_no_link(auth_client, team):
    # A fully-active account (usable password) just gets team membership — no
    # set-password email, and no reset token (which would be a hijack vector).
    active = User.objects.create_user(email="active@example.com", password="RealPass1!")

    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.id}/users/",
        {"name": "Active User", "email": "active@example.com", "role": "developer"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data.get("already_active") is True
    assert "set_password_url" not in resp.data
    assert not PasswordResetRequest.objects.filter(user=active).exists()
    assert TeamMembership.objects.filter(user=active, team=team).exists()
