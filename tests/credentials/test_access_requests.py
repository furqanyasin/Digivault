"""Access requests, temporary shares, and handover.

A request turns "send me the hosting login" into an approved, time-boxed,
audited share; handover is what happens to a leaver's credentials and the list
of passwords to rotate after them.
"""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.audit.models import ActivityLog
from apps.credentials.models import (
    Credential,
    CredentialAccessLog,
    CredentialAccessRequest,
    CredentialShare,
)
from apps.credentials.services import CredentialService
from apps.credentials.tasks import purge_expired_shares

PW = "Pass123!"


def _client_for(user):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": user.email, "password": PW}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="ar_owner@test.com", password=PW)


@pytest.fixture
def team(owner):
    return TeamService.create(name="AR Agency", owner=owner)


@pytest.fixture
def member(team):
    def make(email, role=TeamMembership.Role.DEVELOPER):
        u = User.objects.create_user(email=email, password=PW)
        TeamMembership.objects.create(user=u, team=team, role=role)
        u.active_team = team
        u.save(update_fields=["active_team"])
        return u

    return make


@pytest.fixture
def cred(team, owner):
    return CredentialService.create(
        team=team, label="Acme cPanel", credential_type="cpanel", login_url="",
        username="u", password="s3cret", notes="", created_by=owner,
    )


# ── Expiring shares ───────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestShareExpiry:
    def test_expired_share_grants_nothing(self, cred, member):
        dev = member("dev@ar.io")
        CredentialShare.objects.create(
            credential=cred, user=dev, expires_at=timezone.now() - timedelta(minutes=1)
        )
        assert not Credential.objects.visible_to(dev).exists()
        assert _client_for(dev).post(f"/api/v1/credentials/{cred.pk}/reveal/").status_code == 404

    def test_live_temporary_share_grants(self, cred, member):
        dev = member("dev@ar.io")
        CredentialShare.objects.create(
            credential=cred, user=dev, expires_at=timezone.now() + timedelta(hours=1)
        )
        assert Credential.objects.visible_to(dev).filter(pk=cred.pk).exists()

    def test_manual_share_makes_a_temporary_one_permanent(self, owner, cred, member):
        dev = member("dev@ar.io")
        CredentialShare.objects.create(
            credential=cred, user=dev, expires_at=timezone.now() + timedelta(hours=1)
        )
        _client_for(owner).post(
            f"/api/v1/credentials/{cred.pk}/shares/", {"user_ids": [str(dev.pk)]}, format="json"
        )
        assert CredentialShare.objects.get(credential=cred, user=dev).expires_at is None

    def test_share_with_expiry(self, owner, cred, member):
        dev = member("dev@ar.io")
        _client_for(owner).post(
            f"/api/v1/credentials/{cred.pk}/shares/",
            {"user_ids": [str(dev.pk)], "expires_in_hours": 4}, format="json",
        )
        share = CredentialShare.objects.get(credential=cred, user=dev)
        assert timedelta(hours=3, minutes=59) < share.expires_at - timezone.now() <= timedelta(hours=4)

    def test_purge_removes_only_long_expired(self, cred, member):
        a, b, c = member("a@ar.io"), member("b@ar.io"), member("c@ar.io")
        now = timezone.now()
        CredentialShare.objects.create(credential=cred, user=a, expires_at=now - timedelta(days=2))
        CredentialShare.objects.create(credential=cred, user=b, expires_at=now - timedelta(hours=1))
        CredentialShare.objects.create(credential=cred, user=c)
        assert purge_expired_shares() == 1
        assert set(CredentialShare.objects.values_list("user_id", flat=True)) == {b.pk, c.pk}


# ── Requests ──────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestAccessRequests:
    def test_requestable_lists_only_what_you_cannot_see(self, owner, team, cred, member):
        dev = member("dev@ar.io")
        mine = CredentialService.create(
            team=team, label="Mine", credential_type="custom", login_url="",
            username="", password="", notes="", created_by=dev,
        )
        ids = [r["id"] for r in _client_for(dev).get("/api/v1/credentials/requestable/").data]
        assert str(cred.pk) in ids
        assert str(mine.pk) not in ids
        # Metadata only.
        row = _client_for(dev).get("/api/v1/credentials/requestable/", {"q": "acme"}).data[0]
        assert set(row) == {
            "id", "label", "credential_type", "website_name", "client_name", "department",
        }

    def test_request_approve_and_expire(self, owner, cred, member, django_capture_on_commit_callbacks):
        dev = member("dev@ar.io")
        # Emails go out on commit; run those callbacks when each block exits.
        with django_capture_on_commit_callbacks(execute=True):
            resp = _client_for(dev).post(
                f"/api/v1/credentials/{cred.pk}/access-requests/",
                {"reason": "Fixing their SSL", "hours": 4}, format="json",
            )
        assert resp.status_code == 201, resp.data
        assert any("ar_owner@test.com" in m.to for m in mail.outbox)

        pending = _client_for(owner).get("/api/v1/credentials/access-requests/").data
        assert [r["id"] for r in pending] == [resp.data["id"]]

        with django_capture_on_commit_callbacks(execute=True):
            decided = _client_for(owner).post(
                f"/api/v1/credentials/access-requests/{resp.data['id']}/decide/",
                {"approve": True, "hours": 24, "can_view_password": False}, format="json",
            )
        assert decided.status_code == 200, decided.data
        assert decided.data["status"] == "approved"
        share = CredentialShare.objects.get(credential=cred, user=dev)
        assert share.expires_at is not None and not share.can_view_password
        assert Credential.objects.visible_to(dev).filter(pk=cred.pk).exists()
        assert ActivityLog.objects.filter(action=ActivityLog.Action.CREDENTIAL_ACCESS_APPROVED).exists()
        assert any(dev.email in m.to for m in mail.outbox)

        share.expires_at = timezone.now() - timedelta(seconds=1)
        share.save()
        assert not Credential.objects.visible_to(dev).filter(pk=cred.pk).exists()

    def test_deny(self, owner, cred, member):
        dev = member("dev@ar.io")
        rid = _client_for(dev).post(f"/api/v1/credentials/{cred.pk}/access-requests/", {}, format="json").data["id"]
        resp = _client_for(owner).post(
            f"/api/v1/credentials/access-requests/{rid}/decide/", {"approve": False}, format="json"
        )
        assert resp.data["status"] == "denied"
        assert not CredentialShare.objects.filter(credential=cred, user=dev).exists()

    def test_repeat_request_returns_the_pending_one(self, cred, member):
        dev = member("dev@ar.io")
        c = _client_for(dev)
        first = c.post(f"/api/v1/credentials/{cred.pk}/access-requests/", {}, format="json")
        second = c.post(f"/api/v1/credentials/{cred.pk}/access-requests/", {}, format="json")
        assert first.status_code == 201 and second.status_code == 200
        assert first.data["id"] == second.data["id"]

    def test_cannot_request_what_you_have(self, owner, cred):
        resp = _client_for(owner).post(f"/api/v1/credentials/{cred.pk}/access-requests/", {}, format="json")
        assert resp.status_code == 400

    def test_viewer_cannot_request(self, cred, member):
        viewer = member("v@ar.io", role=TeamMembership.Role.VIEWER)
        resp = _client_for(viewer).post(f"/api/v1/credentials/{cred.pk}/access-requests/", {}, format="json")
        assert resp.status_code == 400

    def test_only_sharers_decide(self, cred, member):
        dev, other = member("dev@ar.io"), member("other@ar.io")
        rid = _client_for(dev).post(f"/api/v1/credentials/{cred.pk}/access-requests/", {}, format="json").data["id"]
        assert _client_for(other).get("/api/v1/credentials/access-requests/").data == []
        resp = _client_for(other).post(
            f"/api/v1/credentials/access-requests/{rid}/decide/", {"approve": True}, format="json"
        )
        assert resp.status_code == 400
        assert not CredentialShare.objects.filter(user=dev).exists()

    def test_approval_never_shortens_a_permanent_share(self, owner, cred, member):
        dev = member("dev@ar.io")
        CredentialShare.objects.create(credential=cred, user=dev, can_view_password=False)
        req = CredentialAccessRequest.objects.create(team=cred.team, credential=cred, requester=dev)
        _client_for(owner).post(
            f"/api/v1/credentials/access-requests/{req.pk}/decide/",
            {"approve": True, "hours": 4, "can_view_password": True}, format="json",
        )
        share = CredentialShare.objects.get(credential=cred, user=dev)
        assert share.expires_at is None
        assert share.can_view_password is True

    def test_requester_cancels_and_sees_history(self, cred, member):
        dev = member("dev@ar.io")
        c = _client_for(dev)
        rid = c.post(f"/api/v1/credentials/{cred.pk}/access-requests/", {}, format="json").data["id"]
        assert c.post(f"/api/v1/credentials/access-requests/{rid}/cancel/").data["status"] == "cancelled"
        mine = c.get("/api/v1/credentials/access-requests/", {"scope": "mine"}).data
        assert [r["status"] for r in mine] == ["cancelled"]


# ── Handover ──────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestHandover:
    def test_summary_lists_what_they_revealed(self, owner, team, cred, member):
        dev = member("dev@ar.io")
        CredentialShare.objects.create(credential=cred, user=dev)
        _client_for(dev).post(f"/api/v1/credentials/{cred.pk}/reveal/")
        CredentialService.create(
            team=team, label="Dev's own", credential_type="custom", login_url="",
            username="", password="", notes="", created_by=dev,
        )
        data = _client_for(owner).get(f"/api/v1/credentials/members/{dev.pk}/summary/").data
        assert data["owned_count"] == 1
        assert data["share_count"] == 1
        assert [r["label"] for r in data["revealed"]] == ["Acme cPanel"]

    def test_handover_moves_and_revokes(self, owner, team, cred, member):
        leaver, heir = member("leaver@ar.io"), member("heir@ar.io")
        own = CredentialService.create(
            team=team, label="Leaver's", credential_type="custom", login_url="",
            username="", password="", notes="", created_by=leaver,
        )
        CredentialShare.objects.create(credential=cred, user=leaver)
        resp = _client_for(owner).post(
            f"/api/v1/credentials/members/{leaver.pk}/handover/",
            {"to_user_id": str(heir.pk), "revoke_shares": True}, format="json",
        )
        assert resp.status_code == 200, resp.data
        assert resp.data == {"moved": 1, "shares_revoked": 1}
        own.refresh_from_db()
        assert own.created_by_id == heir.pk
        assert not Credential.objects.visible_to(leaver).exists()
        assert ActivityLog.objects.filter(action=ActivityLog.Action.CREDENTIAL_HANDOVER).exists()

    def test_developer_cannot_hand_over(self, cred, member):
        dev, other = member("dev@ar.io"), member("other@ar.io")
        resp = _client_for(dev).post(
            f"/api/v1/credentials/members/{other.pk}/handover/",
            {"to_user_id": str(dev.pk)}, format="json",
        )
        assert resp.status_code == 403


@pytest.mark.django_db
def test_share_hides_the_password_unless_asked(owner, cred, member):
    """A share is "can use it"; seeing the password is a separate choice."""
    dev, other = member("hide@ar.io"), member("view@ar.io")
    c = _client_for(owner)
    c.post(f"/api/v1/credentials/{cred.pk}/shares/", {"user_ids": [str(dev.pk)]}, format="json")
    c.post(
        f"/api/v1/credentials/{cred.pk}/shares/",
        {"user_ids": [str(other.pk)], "can_view_password": True}, format="json",
    )
    assert CredentialShare.objects.get(credential=cred, user=dev).can_view_password is False
    assert CredentialShare.objects.get(credential=cred, user=other).can_view_password is True
    assert _client_for(dev).post(f"/api/v1/credentials/{cred.pk}/reveal/").data["password_hidden"] is True
