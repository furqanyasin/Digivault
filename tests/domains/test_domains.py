import pytest
from unittest.mock import patch
from datetime import datetime, timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.domains.models import DomainAlert, DomainInfo
from apps.domains.services import DomainIntelligenceService, DOMAIN_ALERT_THRESHOLDS
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="dom_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Domain Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Domain Site", domain="domtest.io")


class TestDomainIntelligenceService:
    def test_extract_domain_returns_result(self):
        """Service must return a DomainCheckResult without raising."""
        with patch("whois.whois") as mock_whois, \
             patch("socket.gethostbyname", return_value="1.2.3.4"), \
             patch("socket.gethostbyaddr", return_value=("srv.kinsta.com", [], [])), \
             patch("ssl.create_default_context") as mock_ssl:

            mock_whois.return_value = type("W", (), {
                "registrar": "GoDaddy",
                "creation_date": datetime(2020, 1, 1, tzinfo=timezone.utc),
                "expiration_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "name_servers": ["kara.ns.cloudflare.com", "rick.ns.cloudflare.com"],
            })()
            mock_ssl.return_value.__enter__ = lambda s: s
            mock_ssl.return_value.__exit__ = lambda *a: None
            # Make ssl context raise so SSL branch is skipped cleanly
            mock_ssl.return_value.wrap_socket = lambda *a, **k: (_ for _ in ()).throw(
                OSError("no ssl in test")
            )

            result = DomainIntelligenceService.check("domtest.io")

        assert result.registrar == "GoDaddy"
        assert result.hosting_provider == "Kinsta"
        assert result.uses_cloudflare is True

    def test_failed_whois_returns_partial_result(self):
        """Network failure must not raise — returns partial result with error set."""
        with patch("whois.whois", side_effect=Exception("timeout")), \
             patch("socket.gethostbyname", side_effect=OSError("no dns")):
            result = DomainIntelligenceService.check("broken.io")
        assert result.error != ""
        assert result.registrar == ""


@pytest.mark.django_db
class TestDomainAlerts:
    def test_expiry_alerts_created_from_threshold(self, website):
        now = datetime.now(tz=timezone.utc)
        from datetime import timedelta
        expires_soon = now + timedelta(days=25)

        info = DomainInfo.objects.create(
            website=website,
            registrar="GoDaddy",
            expires_at=expires_soon,
        )

        from apps.domains.tasks import _create_expiry_alerts
        _create_expiry_alerts(info)

        # Should have alerts for 90, 60, 30 day thresholds (25 days left → all ≥ 25)
        alert_thresholds = list(
            DomainAlert.objects.filter(
                domain_info=info, alert_type=DomainAlert.AlertType.DOMAIN
            ).values_list("days_until_expiry", flat=True)
        )
        assert 30 in alert_thresholds
        assert 60 in alert_thresholds
        assert 90 in alert_thresholds

    def test_duplicate_alerts_not_created(self, website):
        from datetime import timedelta
        expires_soon = datetime.now(tz=timezone.utc) + timedelta(days=5)
        info = DomainInfo.objects.create(website=website, expires_at=expires_soon)

        from apps.domains.tasks import _create_expiry_alerts
        _create_expiry_alerts(info)
        _create_expiry_alerts(info)  # second call should not duplicate

        count = DomainAlert.objects.filter(
            domain_info=info, alert_type=DomainAlert.AlertType.DOMAIN
        ).count()
        # Should equal number of thresholds crossed — no duplicates
        assert count == len(DOMAIN_ALERT_THRESHOLDS)


@pytest.mark.django_db
class TestDomainAPI:
    def _client(self, user):
        from rest_framework.test import APIClient
        c = APIClient()
        resp = c.post(
            "/api/v1/auth/token/",
            {"email": user.email, "password": "Pass123!"},
            format="json",
        )
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        return c

    def test_domain_info_no_data_returns_404(self, website, owner):
        client = self._client(owner)
        resp = client.get(f"/api/v1/websites/{website.pk}/domain/")
        # No DomainInfo has been gathered yet → 404 (frontend treats as "not checked")
        assert resp.status_code == 404

    def test_domain_refresh_runs_check_and_returns_data(self, website, owner):
        client = self._client(owner)
        from datetime import datetime, timezone as dt_tz

        from apps.domains.services import DomainCheckResult

        fake = DomainCheckResult(
            registrar="GoDaddy",
            expires_at=datetime(2027, 1, 1, tzinfo=dt_tz.utc),
            nameservers=["kara.ns.cloudflare.com"],
            hosting_provider="Kinsta",
            uses_cloudflare=True,
        )
        # The refresh endpoint runs the check synchronously; mock the network call.
        with patch(
            "apps.domains.views.DomainIntelligenceService.check", return_value=fake
        ) as mock_check:
            resp = client.post(f"/api/v1/websites/{website.pk}/domain/refresh/")
        assert resp.status_code == 200
        mock_check.assert_called_once()
        assert resp.data["registrar"] == "GoDaddy"
