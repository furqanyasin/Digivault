"""Public signup, plan limits and the platform owner view."""

import re

import pytest
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import PendingSignup, Team, TeamMembership, User
from apps.accounts.services import TeamService

pytestmark = pytest.mark.django_db

SIGNUP = "/api/v1/auth/signup/"
VERIFY = "/api/v1/auth/verify-email/"


def _signup(client=None, **overrides):
    body = {
        "name": "Ayesha Khan",
        "email": "ayesha@example.com",
        "password": "Strong-Pass-9271",
        "workspace_name": "Khan Studio",
        **overrides,
    }
    return (client or APIClient()).post(SIGNUP, body, format="json")


def _token_from_mail():
    match = re.search(r"verify-email\?token=([\w-]+)", mail.outbox[-1].body)
    assert match, mail.outbox[-1].body
    return match.group(1)


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


# --- signup -------------------------------------------------------------------


def test_signup_creates_nothing_until_the_email_is_confirmed():
    resp = _signup()
    assert resp.status_code == 200
    assert not User.objects.filter(email="ayesha@example.com").exists()
    assert PendingSignup.objects.filter(email="ayesha@example.com").count() == 1
    assert "verify-email?token=" in mail.outbox[-1].body
    # Only the hash is stored.
    token = _token_from_mail()
    assert not PendingSignup.objects.filter(token_hash=token).exists()


def test_confirming_creates_user_and_a_free_workspace_and_signs_in():
    _signup()
    resp = APIClient().post(VERIFY, {"token": _token_from_mail()}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["access"] and resp.data["refresh"]

    user = User.objects.get(email="ayesha@example.com")
    assert user.is_active and user.check_password("Strong-Pass-9271")
    assert user.first_name == "Ayesha" and user.last_name == "Khan"
    team = user.active_team
    assert team.name == "Khan Studio"
    assert team.plan == Team.Plan.FREE and team.require_2fa is False
    assert TeamMembership.objects.get(user=user, team=team).role == "owner"


def test_a_link_works_once():
    _signup()
    token = _token_from_mail()
    assert APIClient().post(VERIFY, {"token": token}, format="json").status_code == 200
    assert APIClient().post(VERIFY, {"token": token}, format="json").status_code == 400


def test_signup_for_an_account_in_use_mails_the_owner_and_changes_nothing():
    owner = User.objects.create_user(email="taken@example.com", password="Original-Pass-1")
    resp = _signup(email="taken@example.com", password="Attacker-Pass-77")
    assert resp.status_code == 200
    assert not PendingSignup.objects.filter(email="taken@example.com").exists()
    assert "already has one" in mail.outbox[-1].body
    owner.refresh_from_db()
    assert owner.check_password("Original-Pass-1")


def test_same_reply_for_new_and_existing_emails():
    User.objects.create_user(email="taken@example.com", password="Original-Pass-1")
    new = _signup(email="fresh@example.com")
    old = _signup(email="taken@example.com")
    assert new.status_code == old.status_code == 200
    assert new.data == old.data


def test_an_account_an_owner_created_but_never_set_up_can_be_claimed():
    squatter = User.objects.create_user(email="squatter@example.com", password="Pass-Squat-1")
    squat_team = TeamService.create(name="Squat", owner=squatter)
    victim = User.objects.create_user(email="real@example.com", password=None)
    victim.set_unusable_password()
    victim.save()
    TeamMembership.objects.create(user=victim, team=squat_team, role="developer")

    _signup(email="real@example.com", password="Real-Owner-Pass-5")
    resp = APIClient().post(VERIFY, {"token": _token_from_mail()}, format="json")
    assert resp.status_code == 200
    victim.refresh_from_db()
    assert victim.check_password("Real-Owner-Pass-5")
    # They land in their own new workspace, not the squatter's.
    assert victim.active_team.owner_id == victim.pk


def test_weak_password_and_disposable_email_are_refused():
    assert _signup(password="123").status_code == 400
    assert _signup(email="x@mailinator.com").status_code == 400


def test_honeypot_fills_create_nothing():
    resp = _signup(company_website="http://spam.example")
    assert resp.status_code == 200
    assert not PendingSignup.objects.exists()


# --- 2FA is optional for signup workspaces -------------------------------------


@override_settings(ALLOW_2FA_BYPASS=False)
def test_free_workspace_owner_logs_in_without_2fa_setup():
    _signup()
    APIClient().post(VERIFY, {"token": _token_from_mail()}, format="json")
    resp = APIClient().post(
        "/api/v1/auth/login/", {"email": "ayesha@example.com", "password": "Strong-Pass-9271"}, format="json",
    )
    assert resp.status_code == 200
    assert "access" in resp.data and not resp.data.get("requires_setup")


@override_settings(ALLOW_2FA_BYPASS=False)
def test_member_of_a_team_that_requires_2fa_must_set_it_up():
    user = User.objects.create_user(email="staff@example.com", password="Staff-Pass-881")
    TeamService.create(name="Agency", owner=user, plan=Team.Plan.INTERNAL, require_2fa=True)
    resp = APIClient().post(
        "/api/v1/auth/login/", {"email": "staff@example.com", "password": "Staff-Pass-881"}, format="json",
    )
    assert resp.data.get("requires_setup") is True
    assert "access" not in resp.data


def test_me_reports_the_2fa_reminder_until_dismissed():
    user = User.objects.create_user(email="me@example.com", password="Me-Pass-12345")
    TeamService.create(name="Mine", owner=user)
    client = _client(user)
    assert client.get("/api/v1/auth/me/").data["show_2fa_reminder"] is True
    client.post("/api/v1/auth/me/2fa-reminder/dismiss/")
    client.force_authenticate(User.objects.get(pk=user.pk))  # fresh row, as a real request loads
    assert client.get("/api/v1/auth/me/").data["show_2fa_reminder"] is False


# --- plans ---------------------------------------------------------------------


def test_owner_cannot_change_their_own_plan():
    user = User.objects.create_user(email="o@example.com", password="Owner-Pass-123")
    team = TeamService.create(name="Mine", owner=user)
    _client(user).patch(f"/api/v1/auth/teams/{team.pk}/", {"plan": "internal"}, format="json")
    team.refresh_from_db()
    assert team.plan == Team.Plan.FREE


@override_settings(ENFORCE_PLAN_LIMITS=True)
def test_free_plan_allows_one_website():
    user = User.objects.create_user(email="o@example.com", password="Owner-Pass-123")
    TeamService.create(name="Mine", owner=user)
    client = _client(user)
    first = client.post("/api/v1/websites/", {"name": "One", "domain": "one.example"}, format="json")
    assert first.status_code == 201, first.data
    second = client.post("/api/v1/websites/", {"name": "Two", "domain": "two.example"}, format="json")
    assert second.status_code == 402
    assert "1 website" in str(second.data)


@override_settings(ENFORCE_PLAN_LIMITS=True)
def test_free_plan_has_one_seat_and_one_free_workspace():
    user = User.objects.create_user(email="o@example.com", password="Owner-Pass-123")
    team = TeamService.create(name="Mine", owner=user)
    client = _client(user)
    resp = client.post(f"/api/v1/auth/teams/{team.pk}/invite/", {"email": "x@example.com"}, format="json")
    assert resp.status_code == 402
    resp = client.post("/api/v1/auth/teams/", {"name": "Second"}, format="json")
    assert resp.status_code == 402


@override_settings(ENFORCE_PLAN_LIMITS=True)
def test_internal_team_has_no_limits():
    user = User.objects.create_user(email="o@example.com", password="Owner-Pass-123")
    TeamService.create(name="Agency", owner=user, plan=Team.Plan.INTERNAL, require_2fa=True)
    client = _client(user)
    for i in range(3):
        resp = client.post("/api/v1/websites/", {"name": f"S{i}", "domain": f"s{i}.example"}, format="json")
        assert resp.status_code == 201


def test_department_made_from_internal_team_stays_internal():
    user = User.objects.create_user(email="o@example.com", password="Owner-Pass-123")
    TeamService.create(name="Agency", owner=user, plan=Team.Plan.INTERNAL, require_2fa=True)
    resp = _client(user).post("/api/v1/auth/teams/", {"name": "SEO dept"}, format="json")
    assert resp.status_code == 201
    dept = Team.objects.get(name="SEO dept")
    assert dept.plan == Team.Plan.INTERNAL and dept.require_2fa


# --- platform owner ------------------------------------------------------------


def test_platform_routes_refuse_team_owners():
    user = User.objects.create_user(email="o@example.com", password="Owner-Pass-123")
    TeamService.create(name="Mine", owner=user)
    client = _client(user)
    for url in ("/api/v1/platform/overview/", "/api/v1/platform/teams/", "/api/v1/platform/users/"):
        assert client.get(url).status_code == 403


def test_platform_owner_sees_every_team_and_changes_a_plan():
    boss = User.objects.create_user(email="boss@example.com", password="Boss-Pass-123")
    call_command("make_platform_owner", "boss@example.com")
    boss.refresh_from_db()
    assert boss.is_superuser and boss.is_staff

    other = User.objects.create_user(email="o@example.com", password="Owner-Pass-123")
    team = TeamService.create(name="Customer", owner=other)
    client = _client(boss)
    names = [t["name"] for t in client.get("/api/v1/platform/teams/").data]
    assert "Customer" in names
    resp = client.patch(f"/api/v1/platform/teams/{team.pk}/", {"plan": "agency"}, format="json")
    assert resp.status_code == 200 and resp.data["plan"] == "agency"
    team.refresh_from_db()
    assert team.plan == "agency"

    resp = client.patch(f"/api/v1/platform/users/{other.pk}/", {"is_active": False}, format="json")
    assert resp.status_code == 200
    other.refresh_from_db()
    assert other.is_active is False
    # Cannot lock themselves out.
    assert client.patch(f"/api/v1/platform/users/{boss.pk}/", {"is_active": False}, format="json").status_code == 400


def test_make_platform_owner_skips_unknown_emails():
    call_command("make_platform_owner", "nobody@example.com")
    assert not User.objects.filter(email="nobody@example.com").exists()


# --- public tools --------------------------------------------------------------


def test_public_tools_refuse_internal_targets():
    client = APIClient()
    assert client.get("/api/v1/public/tools/ssl/", {"domain": "localhost"}).status_code == 400
    assert client.get("/api/v1/public/tools/uptime/", {"url": "http://127.0.0.1:8000/"}).status_code == 400
    assert client.get("/api/v1/public/tools/scripts/", {"url": ""}).status_code == 400


@override_settings(PLATFORM_OWNER_EMAILS=["boss@example.com"])
def test_listed_platform_owner_is_promoted_on_verification():
    _signup(email="boss@example.com")
    resp = APIClient().post(VERIFY, {"token": _token_from_mail()}, format="json")
    assert resp.status_code == 200
    user = User.objects.get(email="boss@example.com")
    assert user.is_superuser and user.is_staff
    # Platform owners always set up 2FA, so no tokens are handed out here.
    assert resp.data.get("login_required") is True
