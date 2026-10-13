"""Password history: the previous password is kept, revealable and restorable.

The agency emergency this answers: a client site breaks after someone rotated
a login, and the old password is still configured somewhere.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.credentials.models import CredentialAccessLog, CredentialPasswordHistory
from apps.credentials.services import CredentialService

PW = "Pass123!"


def _client_for(user):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": user.email, "password": PW}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="ph_owner@test.com", password=PW)


@pytest.fixture
def team(owner):
    return TeamService.create(name="PH Agency", owner=owner)


@pytest.fixture
def cred(team, owner):
    return CredentialService.create(
        team=team, label="Acme WP", credential_type="wordpress", login_url="",
        username="admin", password="first", notes="", created_by=owner,
    )


def _dev(team, email="dev@ph.io"):
    u = User.objects.create_user(email=email, password=PW)
    TeamMembership.objects.create(user=u, team=team, role=TeamMembership.Role.DEVELOPER)
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u


@pytest.mark.django_db
class TestPasswordHistory:
    def test_change_keeps_the_old_password(self, owner, cred):
        CredentialService.update(credential=cred, password="second", updated_by=owner)
        entry = CredentialPasswordHistory.objects.get(credential=cred)
        assert entry.get_password() == "first"
        assert entry.changed_by == owner

    def test_same_password_is_not_a_change(self, owner, cred):
        CredentialService.update(credential=cred, password="first", updated_by=owner)
        CredentialService.update(credential=cred, label="Renamed", updated_by=owner)
        assert not CredentialPasswordHistory.objects.filter(credential=cred).exists()

    def test_capped(self, owner, cred):
        for i in range(CredentialPasswordHistory.KEEP + 3):
            CredentialService.update(credential=cred, password=f"p{i}", updated_by=owner)
        rows = list(CredentialPasswordHistory.objects.filter(credential=cred))
        assert len(rows) == CredentialPasswordHistory.KEEP
        # Newest first, oldest dropped.
        assert rows[0].get_password() == f"p{CredentialPasswordHistory.KEEP + 1}"

    def test_list_reveal_restore(self, owner, cred):
        CredentialService.update(credential=cred, password="second", updated_by=owner)
        c = _client_for(owner)
        rows = c.get(f"/api/v1/credentials/{cred.pk}/password-history/").data
        assert len(rows) == 1 and "password" not in rows[0]
        assert rows[0]["changed_by_email"] == owner.email

        entry_id = rows[0]["id"]
        revealed = c.post(f"/api/v1/credentials/{cred.pk}/password-history/{entry_id}/reveal/")
        assert revealed.data == {"password": "first"}
        assert CredentialAccessLog.objects.filter(
            credential=cred, action=CredentialAccessLog.Action.HISTORY_VIEWED
        ).exists()

        restored = c.post(f"/api/v1/credentials/{cred.pk}/password-history/{entry_id}/restore/")
        assert restored.status_code == 200
        cred.refresh_from_db()
        assert cred.get_password() == "first"
        # The restore is itself undoable: "second" is now in the history.
        assert [r.get_password() for r in cred.password_history.all()][0] == "second"

    def test_use_only_access_cannot_read_history(self, owner, team, cred):
        CredentialService.update(credential=cred, password="second", updated_by=owner)
        dev = _dev(team)
        cred.shares.create(user=dev, can_view_password=False)
        c = _client_for(dev)
        entry_id = c.get(f"/api/v1/credentials/{cred.pk}/password-history/").data[0]["id"]
        resp = c.post(f"/api/v1/credentials/{cred.pk}/password-history/{entry_id}/reveal/")
        assert resp.status_code == 403
        # Nor restore it — that is an edit.
        assert c.post(
            f"/api/v1/credentials/{cred.pk}/password-history/{entry_id}/restore/"
        ).status_code == 403

    def test_invisible_credential_404(self, owner, team, cred):
        CredentialService.update(credential=cred, password="second", updated_by=owner)
        stranger = _dev(team, "stranger@ph.io")
        assert _client_for(stranger).get(
            f"/api/v1/credentials/{cred.pk}/password-history/"
        ).status_code == 404

    def test_extension_save_records_history(self, owner, team, cred):
        from apps.websites.models import Website

        site = Website.objects.create(team=team, name="Acme", domain="acme.io")
        cred.website = site
        cred.save()
        _client_for(owner).post(
            "/api/extension/credentials/save/",
            {"domain": "acme.io", "username": "admin", "password": "changed-in-browser"},
            format="json",
        )
        assert CredentialPasswordHistory.objects.get(credential=cred).get_password() == "first"


@pytest.mark.django_db
class TestItemTypes:
    def test_secure_note_needs_no_login(self, owner, team):
        long_note = "Wi-Fi: Guest / pass\n" * 300  # past the old 2,000-char cap
        resp = _client_for(owner).post("/api/v1/credentials/", {
            "label": "Office network", "credential_type": "secure_note", "notes": long_note,
        }, format="json")
        assert resp.status_code == 201, resp.data
        assert resp.data["department"] == ""

    @pytest.mark.parametrize("ctype, dept", [("server", "dev"), ("database", "dev"), ("api_key", "")])
    def test_kinds_file_by_default(self, owner, team, ctype, dept):
        resp = _client_for(owner).post("/api/v1/credentials/", {
            "label": "x", "credential_type": ctype, "password": "k",
        }, format="json")
        assert resp.status_code == 201, resp.data
        assert resp.data["department"] == dept


@pytest.mark.django_db
def test_extension_site_lookup_skips_non_login_kinds(owner, team):
    from apps.websites.models import Website

    site = Website.objects.create(team=team, name="Acme", domain="acme.io")
    login = CredentialService.create(
        team=team, website=site, label="WP", credential_type="wordpress", login_url="",
        username="a", password="b", notes="", created_by=owner,
    )
    CredentialService.create(
        team=team, website=site, label="Server", credential_type="server",
        login_url="https://acme.io", username="root", password="key", notes="", created_by=owner,
    )
    c = _client_for(owner)
    site_ids = [r["id"] for r in c.get("/api/extension/credentials/", {"domain": "acme.io"}).data]
    assert site_ids == [str(login.pk)]
    # Still listed in the popup's full vault.
    assert len(c.get("/api/extension/credentials/").data) == 2
