import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import Script
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="ext_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Extension Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Ext Site", domain="extsite.io")


@pytest.fixture
def client(owner, team):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": owner.email, "password": "Pass123!"}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


def _make_script(website, provider="google-analytics", category="analytics", is_active=True):
    return Script.objects.create(
        website=website,
        # Distinct per provider via the path, not a `?v=` param: `v` is a
        # volatile cache-buster, so two providers would normalize to one
        # identity and collide on (website, normalized_url).
        src_url=f"https://www.google-analytics.com/{provider}/analytics.js",
        src_domain="www.google-analytics.com",
        provider=provider,
        category=category,
        is_active=is_active,
    )


@pytest.mark.django_db
class TestExtensionLookup:
    def test_unregistered_domain_returns_not_found(self, client):
        resp = client.get("/api/extension/lookup/", {"domain": "notregistered.xyz"})
        assert resp.status_code == 200
        assert resp.data["registered"] is False
        assert resp.data["script_count"] == 0

    def test_registered_domain_returns_scripts(self, client, website):
        _make_script(website, provider="google-analytics")
        _make_script(website, provider="unknown", category="unknown")
        resp = client.get("/api/extension/lookup/", {"domain": "extsite.io"})
        assert resp.status_code == 200
        data = resp.data
        assert data["registered"] is True
        assert data["script_count"] == 2
        assert data["has_unknown"] is True
        assert len(data["scripts"]) == 2

    def test_inactive_scripts_excluded(self, client, website):
        _make_script(website, is_active=True)
        _make_script(website, provider="inactive-script", is_active=False)
        resp = client.get("/api/extension/lookup/", {"domain": "extsite.io"})
        data = resp.data
        assert data["script_count"] == 1

    def test_missing_domain_param_returns_400(self, client):
        resp = client.get("/api/extension/lookup/")
        assert resp.status_code == 400

    def test_domain_strips_https_prefix(self, client, website):
        resp = client.get("/api/extension/lookup/", {"domain": "https://extsite.io/page"})
        data = resp.data
        assert data["registered"] is True

    def test_truncation_at_ten_scripts(self, client, website):
        for i in range(15):
            Script.objects.create(
                website=website,
                src_url=f"https://cdn.example.com/s{i}.js",
                src_domain="cdn.example.com",
                provider=f"provider-{i}",
                category="analytics",
                is_active=True,
            )
        resp = client.get("/api/extension/lookup/", {"domain": "extsite.io"})
        data = resp.data
        assert data["script_count"] == 15
        assert len(data["scripts"]) == 10

    def test_requires_authentication(self, website):
        resp = APIClient().get("/api/extension/lookup/", {"domain": "extsite.io"})
        assert resp.status_code == 401

    def test_other_teams_site_reads_as_unregistered(self, client, db):
        """It used to answer for any team's site, to anyone — a client list oracle."""
        other_owner = User.objects.create_user(email="ext_other@test.com", password="Pass123!")
        other_team = TeamService.create(name="Other Agency", owner=other_owner)
        Website.objects.create(team=other_team, name="Theirs", domain="theirs.io")
        resp = client.get("/api/extension/lookup/", {"domain": "theirs.io"})
        assert resp.data["registered"] is False

    def test_matches_domain_saved_with_scheme_and_www(self, client, team):
        Website.objects.create(team=team, name="Schemed", domain="https://www.schemed.io/")
        resp = client.get("/api/extension/lookup/", {"domain": "schemed.io"})
        assert resp.data["registered"] is True


@pytest.mark.django_db
class TestExtensionDomains:
    def test_lists_team_hosts_bare(self, client, team, website):
        Website.objects.create(team=team, name="Schemed", domain="https://www.schemed.io/")
        resp = client.get("/api/extension/domains/")
        assert resp.status_code == 200
        assert resp.data["domains"] == ["extsite.io", "schemed.io"]

    def test_requires_authentication(self):
        assert APIClient().get("/api/extension/domains/").status_code == 401
