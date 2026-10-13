"""Authenticator codes on credentials, and client/department folders.

The two halves of "the vault works for a team": a shared client account behind
2FA can be signed into by whoever is on the job, and a group tagged with a
department sees that department's logins across every client without anyone
sharing them one by one.
"""

import pyotp
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.clients.models import Client
from apps.credentials.models import Credential, CredentialAccessLog, normalize_totp_secret
from apps.credentials.services import CredentialService
from apps.websites.models import Website

PW = "Pass123!"
SECRET = "JBSWY3DPEHPK3PXP"


def _client_for(user):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": user.email, "password": PW}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="td_owner@test.com", password=PW)


@pytest.fixture
def team(owner):
    return TeamService.create(name="TD Agency", owner=owner)


@pytest.fixture
def acme(team):
    return Client.objects.create(team=team, name="Acme", departments=["seo", "dev"])


@pytest.fixture
def member(team):
    def make(email, role=TeamMembership.Role.DEVELOPER, group=None):
        u = User.objects.create_user(email=email, password=PW)
        TeamMembership.objects.create(user=u, team=team, role=role, sub_team=group)
        u.active_team = team
        u.save(update_fields=["active_team"])
        return u

    return make


def _cred(team, owner, **kw):
    defaults = dict(
        team=team, label="Login", credential_type="custom", login_url="",
        username="u", password="p", notes="", created_by=owner,
    )
    defaults.update(kw)
    return CredentialService.create(**defaults)


# ── normalize_totp_secret ─────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", [
    SECRET,
    "jbsw y3dp ehpk 3pxp",
    "JBSW-Y3DP-EHPK-3PXP",
    f"otpauth://totp/Acme:admin?secret={SECRET}&issuer=Acme",
])
def test_normalize_accepts_what_people_paste(raw):
    assert normalize_totp_secret(raw) == SECRET


@pytest.mark.parametrize("raw", [
    "not!base32",
    f"otpauth://hotp/Acme?secret={SECRET}&counter=1",
    f"otpauth://totp/Acme?secret={SECRET}&digits=8",
    "otpauth://totp/Acme?issuer=Acme",
])
def test_normalize_refuses_what_would_give_wrong_codes(raw):
    with pytest.raises(ValueError):
        normalize_totp_secret(raw)


def test_normalize_blank_means_none():
    assert normalize_totp_secret("  ") == ""


# ── TOTP through the API ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestTotp:
    def test_create_with_totp_and_read_code(self, owner, team):
        c = _client_for(owner)
        resp = c.post("/api/v1/credentials/", {
            "label": "Acme Google", "credential_type": "custom",
            "username": "a", "password": "b", "totp": f"otpauth://totp/x?secret={SECRET}",
        }, format="json")
        assert resp.status_code == 201, resp.data
        assert resp.data["has_totp"] is True
        assert "totp" not in resp.data

        code = c.post(f"/api/v1/credentials/{resp.data['id']}/totp/").data
        assert pyotp.TOTP(SECRET).verify(code["code"], valid_window=1)
        assert code["period"] == 30
        assert 1 <= code["expires_in"] <= 30
        assert CredentialAccessLog.objects.filter(
            credential_id=resp.data["id"], action=CredentialAccessLog.Action.TOTP_CODE
        ).exists()

    def test_secret_never_serialized(self, owner, team):
        cred = _cred(team, owner, totp_secret=SECRET)
        c = _client_for(owner)
        for resp in (
            c.get(f"/api/v1/credentials/{cred.pk}/"),
            c.post(f"/api/v1/credentials/{cred.pk}/reveal/"),
            c.get("/api/v1/credentials/"),
        ):
            assert SECRET not in str(resp.data)

    def test_invalid_secret_rejected(self, owner, team):
        resp = _client_for(owner).post("/api/v1/credentials/", {
            "label": "x", "credential_type": "custom", "totp": "nope!",
        }, format="json")
        assert resp.status_code == 400
        assert "totp" in str(resp.data)

    def test_patch_absent_keeps_blank_removes(self, owner, team):
        cred = _cred(team, owner, totp_secret=SECRET)
        c = _client_for(owner)
        c.patch(f"/api/v1/credentials/{cred.pk}/", {"label": "Renamed"}, format="json")
        cred.refresh_from_db()
        assert cred.get_totp_secret() == SECRET
        c.patch(f"/api/v1/credentials/{cred.pk}/", {"totp": ""}, format="json")
        cred.refresh_from_db()
        assert not cred.has_totp

    def test_no_secret_is_404(self, owner, team):
        cred = _cred(team, owner)
        assert _client_for(owner).post(f"/api/v1/credentials/{cred.pk}/totp/").status_code == 404

    def test_use_only_share_can_read_code(self, owner, team, member):
        """A code is what a teammate needs to finish a sign-in the extension filled."""
        dev = member("dev@td.io")
        cred = _cred(team, owner, totp_secret=SECRET)
        cred.shares.create(user=dev, can_view_password=False)
        assert _client_for(dev).post(f"/api/v1/credentials/{cred.pk}/totp/").status_code == 200

    def test_viewer_and_stranger_cannot(self, owner, team, member):
        cred = _cred(team, owner, totp_secret=SECRET)
        viewer = member("viewer@td.io", role=TeamMembership.Role.VIEWER)
        stranger = member("stranger@td.io")
        assert _client_for(viewer).post(f"/api/v1/credentials/{cred.pk}/totp/").status_code in (403, 404)
        assert _client_for(stranger).post(f"/api/v1/credentials/{cred.pk}/totp/").status_code == 404

    def test_extension_route(self, owner, team):
        cred = _cred(team, owner, totp_secret=SECRET)
        resp = _client_for(owner).post(f"/api/extension/credentials/{cred.pk}/totp/")
        assert resp.status_code == 200
        assert resp.data["code"]


# ── Client folders and default department ─────────────────────────────────────


@pytest.mark.django_db
class TestFiling:
    def test_client_defaults_to_websites_client(self, owner, team, acme):
        site = Website.objects.create(team=team, name="Acme", domain="acme.io", client=acme)
        cred = _cred(team, owner, website=site, credential_type="wordpress")
        assert cred.client_id == acme.pk
        assert cred.department == "dev"

    @pytest.mark.parametrize("ctype, dept", [
        ("google_search_console", "seo"), ("google_ads", "ads"),
        ("cpanel", "dev"), ("custom", ""),
    ])
    def test_department_defaults_from_type(self, owner, team, ctype, dept):
        assert _cred(team, owner, credential_type=ctype).department == dept

    def test_explicit_values_win(self, owner, team, acme):
        resp = _client_for(owner).post("/api/v1/credentials/", {
            "label": "Acme registrar", "credential_type": "cpanel",
            "client_id": str(acme.pk), "department": "",
        }, format="json")
        assert resp.status_code == 201, resp.data
        assert resp.data["client_id"] == str(acme.pk)
        assert resp.data["client_name"] == "Acme"
        assert resp.data["department"] == ""

    def test_other_teams_client_refused(self, owner, team):
        other = TeamService.create(
            name="Other", owner=User.objects.create_user(email="o@td.io", password=PW)
        )
        theirs = Client.objects.create(team=other, name="Theirs")
        resp = _client_for(owner).post("/api/v1/credentials/", {
            "label": "x", "credential_type": "custom", "client_id": str(theirs.pk),
        }, format="json")
        assert resp.status_code == 400

    def test_patch_moves_between_folders(self, owner, team, acme):
        cred = _cred(team, owner)
        _client_for(owner).patch(f"/api/v1/credentials/{cred.pk}/", {
            "client_id": str(acme.pk), "department": "seo",
        }, format="json")
        cred.refresh_from_db()
        assert (cred.client_id, cred.department) == (acme.pk, "seo")
