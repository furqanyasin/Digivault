"""The extension's credential routes: who may change what, and which site gets
which password.

Each test here pins a hole that was open in production: a viewer overwriting a
password through the save prompt, a lookalike domain being offered the real
site's login, and password-only tokens that skipped mandatory 2FA.
"""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.audit.models import ActivityLog
from apps.credentials.models import Credential
from apps.credentials.services import CredentialService
from apps.websites.models import Website

PW = "Pass123!"


def _client_for(user):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": user.email, "password": PW}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="xs_owner@test.com", password=PW)


@pytest.fixture
def team(owner):
    return TeamService.create(name="XS Agency", owner=owner)


@pytest.fixture
def member(team):
    def make(email, role):
        u = User.objects.create_user(email=email, password=PW)
        TeamMembership.objects.create(user=u, team=team, role=role)
        u.active_team = team
        u.save(update_fields=["active_team"])
        return u

    return make


@pytest.fixture
def website(team):
    # Saved with a scheme and www — one of the three spellings users type.
    return Website.objects.create(team=team, name="Acme", domain="https://www.acme.com/")


@pytest.fixture
def credential(team, website, owner):
    return CredentialService.create(
        team=team, website=website, label="WP admin", credential_type="wordpress",
        login_url="https://acme.com/wp-admin", username="admin",
        password="original", notes="", created_by=owner,
    )


def _save(client, password="changed", username="admin", domain="acme.com"):
    return client.post(
        "/api/extension/credentials/save/",
        {"domain": domain, "username": username, "password": password},
        format="json",
    )


@pytest.mark.django_db
class TestSavePermissions:
    @pytest.mark.parametrize("role", [TeamMembership.Role.VIEWER, TeamMembership.Role.DEVELOPER])
    def test_non_creator_cannot_overwrite(self, member, credential, role):
        user = member(f"{role}@test.com", role)
        resp = _save(_client_for(user))
        assert resp.status_code == 403
        credential.refresh_from_db()
        assert credential.get_password() == "original"

    def test_creator_can_update_and_it_is_audited(self, owner, credential):
        resp = _save(_client_for(owner))
        assert resp.status_code == 200
        assert resp.data["action"] == "updated"
        credential.refresh_from_db()
        assert credential.get_password() == "changed"
        assert ActivityLog.objects.filter(
            action=ActivityLog.Action.CREDENTIAL_UPDATED, resource_id=str(credential.pk)
        ).exists()

    def test_manager_can_update(self, member, credential):
        manager = member("mgr@test.com", TeamMembership.Role.MANAGER)
        assert _save(_client_for(manager)).status_code == 200

    def test_new_username_creates_and_is_audited(self, member, website):
        dev = member("dev@test.com", TeamMembership.Role.DEVELOPER)
        resp = _save(_client_for(dev), username="someone-new")
        assert resp.status_code == 201
        created = Credential.objects.get(pk=resp.data["credential_id"])
        assert created.website_id == website.pk
        assert created.created_by_id == dev.pk
        assert ActivityLog.objects.filter(
            action=ActivityLog.Action.CREDENTIAL_CREATED, resource_id=str(created.pk)
        ).exists()

    def test_finds_website_saved_with_scheme_and_www(self, owner, website):
        resp = _save(_client_for(owner), username="fresh")
        assert resp.status_code == 201


@pytest.mark.django_db
class TestLookupMatching:
    def _lookup(self, user, domain):
        return _client_for(user).get("/api/extension/credentials/", {"domain": domain}).data

    def test_matches_website_saved_with_scheme_and_www(self, owner, credential):
        assert [c["id"] for c in self._lookup(owner, "acme.com")] == [str(credential.pk)]
        assert [c["id"] for c in self._lookup(owner, "www.acme.com")] == [str(credential.pk)]

    def test_lookalike_domain_gets_nothing(self, owner, team):
        """`acme.co` used to match a stored `https://acme.com/...` by substring."""
        CredentialService.create(
            team=team, website=None, label="Hosting", credential_type="cpanel",
            login_url="https://acme.com:2083/login", username="u", password="p",
            notes="", created_by=owner,
        )
        assert self._lookup(owner, "acme.co") == []

    def test_standalone_login_url_still_matches_its_host(self, owner, team):
        cred = CredentialService.create(
            team=team, website=None, label="Hosting", credential_type="cpanel",
            login_url="https://panel.host.io:2083/login", username="u", password="p",
            notes="", created_by=owner,
        )
        assert [c["id"] for c in self._lookup(owner, "panel.host.io")] == [str(cred.pk)]
        assert self._lookup(owner, "host.io") == []


@pytest.mark.django_db
class TestPasswordOnlyTokens:
    def test_api_token_refused_without_2fa_bypass(self, owner):
        with override_settings(ALLOW_2FA_BYPASS=False):
            resp = APIClient().post(
                "/api/v1/auth/token/", {"email": owner.email, "password": PW}, format="json"
            )
        assert resp.status_code == 403
        assert "access" not in (resp.data or {})

    def test_extension_signs_in_with_password_alone(self, owner, team):
        """A product decision: the extension takes no authenticator code."""
        with override_settings(ALLOW_2FA_BYPASS=False):
            resp = APIClient().post(
                "/api/extension/token/", {"email": owner.email, "password": PW}, format="json"
            )
        assert resp.status_code == 200
        assert resp.data["access"]
        assert ActivityLog.objects.filter(
            action=ActivityLog.Action.AUTH_LOGIN, actor=owner,
            description__icontains="extension",
        ).exists()

    def test_extension_failed_sign_in_is_audited(self, owner, team):
        resp = APIClient().post(
            "/api/extension/token/", {"email": owner.email, "password": "wrong"}, format="json"
        )
        assert resp.status_code == 401
        assert ActivityLog.objects.filter(
            action=ActivityLog.Action.AUTH_LOGIN_FAILED, description__icontains=owner.email,
        ).exists()

    def test_extension_refuses_temp_password(self, owner):
        owner.must_change_password = True
        owner.save(update_fields=["must_change_password"])
        resp = APIClient().post(
            "/api/extension/token/", {"email": owner.email, "password": PW}, format="json"
        )
        assert resp.status_code == 403
        assert "access" not in (resp.data or {})
