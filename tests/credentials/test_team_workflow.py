"""Saving any site, who has access, per-credential activity, broken logins,
and change notices."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamMembership, User
from apps.accounts.services import TeamService
from apps.audit.models import ActivityLog
from apps.clients.models import Client
from apps.credentials.models import Credential, CredentialAccessLog, CredentialShare
from apps.credentials.services import CredentialService

PW = "Pass123!"


def _client_for(user):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": user.email, "password": PW}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="tw_owner@test.com", password=PW, first_name="Olive")


@pytest.fixture
def team(owner):
    return TeamService.create(name="TW Agency", owner=owner)


@pytest.fixture
def member(team):
    def make(email, role=TeamMembership.Role.DEVELOPER, group=None):
        u = User.objects.create_user(email=email, password=PW)
        TeamMembership.objects.create(user=u, team=team, role=role, sub_team=group)
        u.active_team = team
        u.save(update_fields=["active_team"])
        return u

    return make


@pytest.fixture
def cred(team, owner):
    return CredentialService.create(
        team=team, label="Acme cPanel", credential_type="cpanel", login_url="https://acme.io:2083",
        username="u", password="old", notes="", created_by=owner,
    )


# ── Save logins on any site ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestSaveAnySite:
    def _save(self, user, password="s3", domain="app.semrush.com", username="seo@agency.io"):
        return _client_for(user).post(
            "/api/extension/credentials/save/",
            {"domain": domain, "username": username, "password": password,
             "login_url": f"https://{domain}/login"},
            format="json",
        )

    def test_unregistered_site_saves_standalone(self, owner, team):
        resp = self._save(owner)
        assert resp.status_code == 201, resp.data
        c = Credential.objects.get(pk=resp.data["credential_id"])
        assert c.website_id is None
        assert c.label == "app.semrush.com login"
        assert c.login_url == "https://app.semrush.com/login"

    def test_second_save_updates_the_same_standalone(self, owner, team):
        first = self._save(owner, password="one").data["credential_id"]
        resp = self._save(owner, password="two")
        assert resp.data == {"action": "updated", "credential_id": first}
        assert Credential.objects.get(pk=first).get_password() == "two"

    def test_and_autofill_finds_it_next_time(self, owner, team):
        self._save(owner)
        found = _client_for(owner).get(
            "/api/extension/credentials/", {"domain": "app.semrush.com"}
        ).data
        assert [c["label"] for c in found] == ["app.semrush.com login"]


# ── Who has access ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestWhoHasAccess:
    def test_lists_every_route(self, owner, team, cred, member):
        from apps.credentials.models import SubTeamCredentialGrant, VaultFolder

        folder = VaultFolder.objects.create(team=team, name="Web")
        cred.folder = folder
        cred.save()
        group = SubTeam.objects.create(team=team, name="Web Team")
        SubTeamCredentialGrant.objects.create(sub_team=group, scope="folder", folder=folder)
        web = member("web@tw.io", group=group)
        shared = member("shared@tw.io")
        CredentialShare.objects.create(
            credential=cred, user=shared, can_view_password=False,
            expires_at=timezone.now() + timedelta(hours=4),
        )
        member("nobody@tw.io")  # no route -> not listed

        rows = {r["email"]: r for r in _client_for(owner).get(f"/api/v1/credentials/{cred.pk}/access/").data}
        assert set(rows) == {owner.email, web.email, shared.email}
        assert {r["kind"] for r in rows[owner.email]["routes"]} == {"role", "creator"}
        assert rows[web.email]["routes"][0]["kind"] == "folder"
        assert rows[web.email]["can_view_password"] is False
        share_route = rows[shared.email]["routes"][0]
        assert share_route["kind"] == "share" and share_route["expires_at"] is not None

    def test_expired_share_is_not_access(self, owner, team, cred, member):
        gone = member("gone@tw.io")
        CredentialShare.objects.create(
            credential=cred, user=gone, expires_at=timezone.now() - timedelta(minutes=1)
        )
        emails = [r["email"] for r in _client_for(owner).get(f"/api/v1/credentials/{cred.pk}/access/").data]
        assert gone.email not in emails

    def test_plain_member_with_a_share_cannot_audit(self, cred, member):
        dev = member("dev@tw.io")
        CredentialShare.objects.create(credential=cred, user=dev)
        c = _client_for(dev)
        assert c.get(f"/api/v1/credentials/{cred.pk}/access/").status_code == 403
        assert c.get(f"/api/v1/credentials/{cred.pk}/activity/").status_code == 403

    def test_activity_lists_this_credentials_log(self, owner, cred):
        c = _client_for(owner)
        c.post(f"/api/v1/credentials/{cred.pk}/reveal/")
        rows = c.get(f"/api/v1/credentials/{cred.pk}/activity/").data
        assert rows[0]["action"] == CredentialAccessLog.Action.VIEWED
        assert rows[0]["user_email"] == owner.email


# ── Broken logins ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestBroken:
    def test_report_flags_emails_and_audits(self, owner, team, cred, member, django_capture_on_commit_callbacks):
        dev = member("dev@tw.io")
        CredentialShare.objects.create(credential=cred, user=dev)
        with django_capture_on_commit_callbacks(execute=True):
            resp = _client_for(dev).post(
                f"/api/v1/credentials/{cred.pk}/report-broken/", {"note": "Locked out"}, format="json"
            )
        assert resp.status_code == 200
        assert resp.data["broken"]["by_email"] == dev.email
        assert resp.data["broken"]["note"] == "Locked out"
        assert [m.to for m in mail.outbox] == [[owner.email]]
        assert ActivityLog.objects.filter(action=ActivityLog.Action.CREDENTIAL_REPORTED_BROKEN).exists()

    def test_second_report_does_not_email_again(self, owner, cred, django_capture_on_commit_callbacks):
        other = User.objects.create_user(email="m@tw.io", password=PW)
        TeamMembership.objects.create(user=other, team=cred.team, role=TeamMembership.Role.MANAGER)
        other.active_team = cred.team
        other.save()
        with django_capture_on_commit_callbacks(execute=True):
            _client_for(other).post(f"/api/v1/credentials/{cred.pk}/report-broken/", {}, format="json")
            _client_for(other).post(f"/api/v1/credentials/{cred.pk}/report-broken/", {}, format="json")
        assert len(mail.outbox) == 1

    def test_password_change_clears_it(self, owner, cred):
        cred.reported_broken_at = timezone.now()
        cred.save()
        CredentialService.update(credential=cred, password="new", updated_by=owner)
        cred.refresh_from_db()
        assert cred.reported_broken_at is None

    def test_mark_fixed_needs_edit_rights(self, owner, cred, member):
        dev = member("dev@tw.io")
        CredentialShare.objects.create(credential=cred, user=dev)
        cred.reported_broken_at = timezone.now()
        cred.save()
        assert _client_for(dev).post(f"/api/v1/credentials/{cred.pk}/mark-fixed/").status_code == 403
        resp = _client_for(owner).post(f"/api/v1/credentials/{cred.pk}/mark-fixed/")
        assert resp.data["broken"] is None

    def test_extension_route(self, owner, cred):
        resp = _client_for(owner).post(f"/api/extension/credentials/{cred.pk}/report-broken/", {}, format="json")
        assert resp.status_code == 200


# ── Change notices ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestChangeNotice:
    def test_recent_users_are_told(self, owner, team, cred, member, django_capture_on_commit_callbacks):
        user_a, idle = member("a@tw.io"), member("idle@tw.io")
        for u in (user_a, idle):
            CredentialShare.objects.create(credential=cred, user=u)
        CredentialAccessLog.objects.create(credential=cred, user=user_a, action="autofill")
        with django_capture_on_commit_callbacks(execute=True):
            CredentialService.update(credential=cred, password="rotated", updated_by=owner)
        assert [m.to for m in mail.outbox] == [[user_a.email]]
        assert "rotated" not in mail.outbox[0].body  # never the password itself

    def test_not_the_changer_and_not_on_same_password(self, owner, cred, django_capture_on_commit_callbacks):
        CredentialAccessLog.objects.create(credential=cred, user=owner, action="viewed")
        with django_capture_on_commit_callbacks(execute=True):
            CredentialService.update(credential=cred, password="old", updated_by=owner)
            CredentialService.update(credential=cred, password="new", updated_by=owner)
        assert mail.outbox == []

    def test_import_does_not_send(self, owner, cred, member, django_capture_on_commit_callbacks):
        user_a = member("a@tw.io")
        CredentialShare.objects.create(credential=cred, user=user_a)
        CredentialAccessLog.objects.create(credential=cred, user=user_a, action="viewed")
        with django_capture_on_commit_callbacks(execute=True):
            CredentialService.update(credential=cred, password="x", updated_by=owner, notify_users=False)
        assert mail.outbox == []


# ── Activity Log reaches the vault ────────────────────────────────────────────


@pytest.mark.django_db
def test_client_filter_finds_a_websiteless_credential(owner, team):
    acme = Client.objects.create(team=team, name="Acme")
    c = _client_for(owner)
    created = c.post("/api/v1/credentials/", {
        "label": "Acme GSC", "credential_type": "google_search_console", "client_id": str(acme.pk),
    }, format="json").data
    c.post(f"/api/v1/credentials/{created['id']}/reveal/")
    rows = c.get("/api/v1/logs/", {"client_id": str(acme.pk)}).data
    descriptions = [r["description"] for r in rows]
    assert any("Acme GSC" in d for d in descriptions)


@pytest.mark.django_db
def test_totp_read_is_in_the_activity_log(owner, team):
    cred = CredentialService.create(
        team=team, label="Shared Semrush", credential_type="semrush", login_url="",
        username="u", password="p", notes="", created_by=owner, totp_secret="JBSWY3DPEHPK3PXP",
    )
    _client_for(owner).post(f"/api/v1/credentials/{cred.pk}/totp/")
    assert ActivityLog.objects.filter(action=ActivityLog.Action.CREDENTIAL_TOTP_READ).exists()
