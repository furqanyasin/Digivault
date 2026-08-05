"""Domain, SSL and hosting expiry alerts reach the shared team channel."""
from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.domains.models import DomainAlert, DomainInfo
from apps.domains.notifications import deliver_domain_alert
from apps.websites.models import Website


@pytest.fixture
def alert(db):
    owner = User.objects.create_user(email="dnsowner@x.io", password="Pass123!")
    team = TeamService.create(name="DNS Co", owner=owner)
    team.clickup_chat_url = "https://app.clickup.com/9001/chat/r/chan-77"
    team.clickup_api_token = "pk_test"
    team.save()
    website = Website.objects.create(team=team, name="Example", domain="example.com")
    info, _ = DomainInfo.objects.get_or_create(website=website)
    return DomainAlert.objects.create(domain_info=info, alert_type="ssl", days_until_expiry=7)


def test_an_expiry_alert_announces_in_the_team_channel(alert):
    with patch("apps.integrations.chat.notify_problem") as np:
        deliver_domain_alert(alert)

    assert np.called
    assert np.call_args.kwargs["subject"] == f"domain:{alert.domain_info_id}:ssl"


def test_the_chat_post_happens_even_with_no_notification_channels(alert):
    """resolve_channels() returns nothing here — the team feed still fires."""
    with patch("apps.integrations.chat.notify_problem") as np:
        delivered = deliver_domain_alert(alert)

    assert np.called
    assert delivered is False  # no configured channels, so the alert stays unsent


def test_a_chat_failure_does_not_block_the_rest_of_delivery(alert):
    with patch("apps.integrations.chat.notify_problem", side_effect=RuntimeError("boom")):
        # Must not raise out of deliver_domain_alert.
        deliver_domain_alert(alert)
