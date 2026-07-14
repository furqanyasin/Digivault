import json
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.credentials.services import CredentialService
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="ec_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="EC Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="EC Site", domain="ecsite.io")


@pytest.fixture
def credential(website, owner):
    return CredentialService.create(
        website=website,
        label="WordPress Admin",
        credential_type="wordpress",
        login_url="https://ecsite.io/wp-admin",
        username="admin",
        password="secret",
        notes="",
        created_by=owner,
    )


def _auth_client(user):
    client = APIClient()
    resp = client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "Pass123!"},
        format="json",
    )
    token_data = json.loads(resp.content)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_data['data']['access']}")
    return client


@pytest.mark.django_db
class TestExtensionCredentialsLookup:
    def test_unauthenticated_returns_401(self):
        client = APIClient()
        resp = client.get("/api/extension/credentials/", {"domain": "ecsite.io"})
        assert resp.status_code == 401

    def test_missing_domain_returns_full_vault(self, owner, team, website, credential):
        """No domain param → the whole team vault (backs the 'All items' tab)."""
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/")
        assert resp.status_code == 200
        data = json.loads(resp.content)["data"]
        assert len(data) == 1
        assert data[0]["label"] == "WordPress Admin"

    def test_missing_domain_still_excludes_password(self, owner, team, website, credential):
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/")
        item = json.loads(resp.content)["data"][0]
        assert "password" not in item
        assert "username" not in item

    def test_returns_credentials_for_matching_domain(self, owner, team, website, credential):
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/", {"domain": "ecsite.io"})
        assert resp.status_code == 200
        data = json.loads(resp.content)["data"]
        assert len(data) == 1
        assert data[0]["label"] == "WordPress Admin"
        assert data[0]["credential_type"] == "wordpress"
        assert data[0]["login_url"] == "https://ecsite.io/wp-admin"

    def test_response_never_contains_password(self, owner, team, website, credential):
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/", {"domain": "ecsite.io"})
        item = json.loads(resp.content)["data"][0]
        assert "password" not in item
        assert "_password" not in item
        assert "username" not in item

    def test_unknown_domain_returns_empty_list(self, owner, team):
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/", {"domain": "unknown.xyz"})
        assert resp.status_code == 200
        assert json.loads(resp.content)["data"] == []

    def test_domain_match_is_case_insensitive(self, owner, team, website, credential):
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/", {"domain": "ECSITE.IO"})
        assert resp.status_code == 200
        assert len(json.loads(resp.content)["data"]) == 1

    def test_www_variant_matches(self, owner, team, website, credential):
        """A www. host should match a bare website domain (and vice-versa)."""
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/", {"domain": "www.ecsite.io"})
        assert resp.status_code == 200
        assert len(json.loads(resp.content)["data"]) == 1

    def test_standalone_credential_matched_by_login_url(self, owner, team):
        """A standalone (no-website) credential autofills on its login_url host."""
        CredentialService.create(
            team=team,
            label="SiteGround",
            credential_type="siteground",
            login_url="https://my.siteground.com/login",
            username="host-admin",
            password="secret",
            notes="",
            created_by=owner,
        )
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/", {"domain": "my.siteground.com"})
        assert resp.status_code == 200
        data = json.loads(resp.content)["data"]
        assert len(data) == 1
        assert data[0]["label"] == "SiteGround"

    def test_credentials_from_other_team_not_returned(self, owner, team, website, credential):
        other_owner = User.objects.create_user(email="other@test.com", password="Pass123!")
        TeamService.create(name="Other Agency", owner=other_owner)
        client = _auth_client(other_owner)
        resp = client.get("/api/extension/credentials/", {"domain": "ecsite.io"})
        assert resp.status_code == 200
        assert json.loads(resp.content)["data"] == []
