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


def _make_script(website, provider="google-analytics", category="analytics", is_active=True):
    return Script.objects.create(
        website=website,
        src_url=f"https://www.google-analytics.com/analytics.js?v={provider}",
        src_domain="www.google-analytics.com",
        provider=provider,
        category=category,
        is_active=is_active,
    )


@pytest.mark.django_db
class TestExtensionLookup:
    def test_unregistered_domain_returns_not_found(self):
        client = APIClient()
        resp = client.get("/api/extension/lookup/", {"domain": "notregistered.xyz"})
        assert resp.status_code == 200
        assert resp.data["registered"] is False
        assert resp.data["script_count"] == 0

    def test_registered_domain_returns_scripts(self, website):
        _make_script(website, provider="google-analytics")
        _make_script(website, provider="unknown", category="unknown")
        client = APIClient()
        resp = client.get("/api/extension/lookup/", {"domain": "extsite.io"})
        assert resp.status_code == 200
        data = resp.data
        assert data["registered"] is True
        assert data["script_count"] == 2
        assert data["has_unknown"] is True
        assert len(data["scripts"]) == 2

    def test_inactive_scripts_excluded(self, website):
        _make_script(website, is_active=True)
        _make_script(website, provider="inactive-script", is_active=False)
        client = APIClient()
        resp = client.get("/api/extension/lookup/", {"domain": "extsite.io"})
        data = resp.data
        assert data["script_count"] == 1

    def test_missing_domain_param_returns_400(self):
        client = APIClient()
        resp = client.get("/api/extension/lookup/")
        assert resp.status_code == 400

    def test_domain_strips_https_prefix(self, website):
        client = APIClient()
        resp = client.get("/api/extension/lookup/", {"domain": "https://extsite.io/page"})
        data = resp.data
        assert data["registered"] is True

    def test_truncation_at_ten_scripts(self, website):
        for i in range(15):
            Script.objects.create(
                website=website,
                src_url=f"https://cdn.example.com/s{i}.js",
                src_domain="cdn.example.com",
                provider=f"provider-{i}",
                category="analytics",
                is_active=True,
            )
        client = APIClient()
        resp = client.get("/api/extension/lookup/", {"domain": "extsite.io"})
        data = resp.data
        assert data["script_count"] == 15
        assert len(data["scripts"]) == 10
