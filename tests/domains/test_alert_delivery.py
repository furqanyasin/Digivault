import pytest
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.domains.models import DomainAlert, DomainInfo
from apps.domains.notifications import deliver_domain_alert
from apps.domains.tasks import _deliver_unsent_alerts
from apps.monitors.models import NotificationChannel
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="da@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="DA Agency", owner=owner)


@pytest.fixture
def site(team):
    return Website.objects.create(team=team, name="DA Site", domain="dasite.com")


@pytest.fixture
def domain_info(site):
    di, _ = DomainInfo.objects.update_or_create(
        website=site,
        defaults={"expires_at": timezone.now() + timedelta(days=5)},
    )
    return di


@pytest.fixture
def email_channel(team):
    return NotificationChannel.objects.create(
        team=team, name="Email", channel_type="email",
        config={"addresses": ["ops@dasite.com"]},
    )


@pytest.mark.django_db
class TestDomainAlertDelivery:
    def test_delivers_to_email_channel_and_marks_sent(self, domain_info, email_channel):
        alert = DomainAlert.objects.create(
            domain_info=domain_info, alert_type=DomainAlert.AlertType.DOMAIN,
            days_until_expiry=7,
        )
        with patch("apps.domains.notifications.send_mail") as mock_send:
            result = deliver_domain_alert(alert)
        assert result is True
        mock_send.assert_called_once()
        alert.refresh_from_db()
        assert alert.sent is True
        assert alert.sent_at is not None

    def test_no_channels_leaves_alert_unsent(self, domain_info):
        alert = DomainAlert.objects.create(
            domain_info=domain_info, alert_type=DomainAlert.AlertType.DOMAIN,
            days_until_expiry=7,
        )
        result = deliver_domain_alert(alert)
        assert result is False
        alert.refresh_from_db()
        assert alert.sent is False

    def test_failed_delivery_leaves_alert_unsent(self, domain_info, email_channel):
        alert = DomainAlert.objects.create(
            domain_info=domain_info, alert_type=DomainAlert.AlertType.DOMAIN,
            days_until_expiry=7,
        )
        with patch("apps.domains.notifications.send_mail", side_effect=Exception("SMTP down")):
            result = deliver_domain_alert(alert)
        assert result is False
        alert.refresh_from_db()
        assert alert.sent is False

    def test_deliver_unsent_sends_most_urgent_and_supersedes_rest(self, domain_info, email_channel):
        for days in (30, 14, 7):
            DomainAlert.objects.create(
                domain_info=domain_info, alert_type=DomainAlert.AlertType.DOMAIN,
                days_until_expiry=days,
            )
        with patch("apps.domains.notifications.send_mail") as mock_send:
            _deliver_unsent_alerts(domain_info)
        assert mock_send.call_count == 1
        assert domain_info.alerts.filter(sent=False).count() == 0

    def test_alert_scoped_to_owning_team_channels(self, domain_info, email_channel):
        other_owner = User.objects.create_user(email="other_da@test.com", password="Pass123!")
        other_team = TeamService.create(name="Other DA", owner=other_owner)
        NotificationChannel.objects.create(
            team=other_team, name="Other", channel_type="email",
            config={"addresses": ["x@x.com"]},
        )
        alert = DomainAlert.objects.create(
            domain_info=domain_info, alert_type=DomainAlert.AlertType.DOMAIN,
            days_until_expiry=7,
        )
        with patch("apps.domains.notifications.send_mail") as mock_send:
            deliver_domain_alert(alert)
        mock_send.assert_called_once()
        recipient_list = mock_send.call_args[0][3]
        assert "ops@dasite.com" in recipient_list
        assert "x@x.com" not in recipient_list
