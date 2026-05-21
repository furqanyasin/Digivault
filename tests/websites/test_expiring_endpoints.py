import pytest
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.domains.models import DomainInfo
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="exp@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Expiry Agency", owner=owner)


@pytest.fixture
def auth_client(owner, team):
    client = APIClient()
    resp = client.post(
        "/api/v1/auth/token/",
        {"email": owner.email, "password": "Pass123!"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return client


@pytest.mark.django_db
class TestExpiringEndpoints:
    def test_expiring_domains_returns_sites_within_30_days(self, owner, team, auth_client):
        site = Website.objects.create(team=team, name="ExpiringDomain", domain="exp.com")
        DomainInfo.objects.create(
            website=site,
            expires_at=timezone.now() + timedelta(days=15),
        )
        resp = auth_client.get("/api/v1/websites/expiring-domains/")
        assert resp.status_code == 200
        data = resp.data
        assert any(d["domain"] == "exp.com" for d in data)

    def test_expiring_domains_excludes_sites_beyond_30_days(self, owner, team, auth_client):
        site = Website.objects.create(team=team, name="FarExpiry", domain="far.com")
        DomainInfo.objects.create(
            website=site,
            expires_at=timezone.now() + timedelta(days=60),
        )
        resp = auth_client.get("/api/v1/websites/expiring-domains/")
        assert resp.status_code == 200
        data = resp.data
        assert not any(d["domain"] == "far.com" for d in data)

    def test_expiring_ssl_returns_sites_within_14_days(self, owner, team, auth_client):
        site = Website.objects.create(team=team, name="ExpiringSsl", domain="ssl.com")
        DomainInfo.objects.create(
            website=site,
            ssl_expires_at=timezone.now() + timedelta(days=7),
        )
        resp = auth_client.get("/api/v1/websites/expiring-ssl/")
        assert resp.status_code == 200
        data = resp.data
        assert any(d["domain"] == "ssl.com" for d in data)

    def test_expiring_ssl_excludes_sites_beyond_14_days(self, owner, team, auth_client):
        site = Website.objects.create(team=team, name="FarSsl", domain="farssl.com")
        DomainInfo.objects.create(
            website=site,
            ssl_expires_at=timezone.now() + timedelta(days=30),
        )
        resp = auth_client.get("/api/v1/websites/expiring-ssl/")
        assert resp.status_code == 200
        data = resp.data
        assert not any(d["domain"] == "farssl.com" for d in data)

    def test_expiring_domains_isolated_to_team(self, owner, team, auth_client):
        other_owner = User.objects.create_user(email="other_exp@test.com", password="Pass123!")
        other_team = TeamService.create(name="Other Expiry", owner=other_owner)
        other_site = Website.objects.create(team=other_team, name="OtherSite", domain="other.com")
        DomainInfo.objects.create(
            website=other_site,
            expires_at=timezone.now() + timedelta(days=5),
        )
        resp = auth_client.get("/api/v1/websites/expiring-domains/")
        assert resp.status_code == 200
        data = resp.data
        assert not any(d["domain"] == "other.com" for d in data)
