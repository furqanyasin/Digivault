"""Phase 1.2 (parity) — Slack delivery for uptime monitors."""

from unittest.mock import MagicMock, patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor, NotificationChannel


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="slack_mon@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Slack Mon Agency", owner=owner)


@pytest.fixture
def monitor(team):
    return Monitor.objects.create(
        team=team, name="Site", url="https://site.io", monitor_type="http"
    )


@pytest.fixture
def slack_channel(team):
    return NotificationChannel.objects.create(
        team=team, name="Ops Slack", channel_type="slack",
        config={"webhook_url": "https://hooks.slack.com/services/XXX"},
    )


@pytest.mark.django_db
def test_slack_sender_posts_to_webhook(monitor, slack_channel):
    from apps.monitors.notifications import dispatch

    with patch("apps.monitors.notifications.urllib.request.urlopen") as mock_open:
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = resp

        dispatch(slack_channel, monitor, "up", "down")
        mock_open.assert_called_once()


@pytest.mark.django_db
def test_slack_channel_type_is_valid():
    assert "slack" in dict(NotificationChannel.ChannelType.choices)


@pytest.mark.django_db
def test_slack_channel_test_endpoint(team, owner, slack_channel):
    from rest_framework.test import APIClient

    c = APIClient()
    resp = c.post(
        "/api/v1/auth/token/",
        {"email": owner.email, "password": "Pass123!"},
        format="json",
    )
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    with patch("apps.monitors.views.urllib.request.urlopen") as mock_open:
        r = MagicMock()
        r.status = 200
        r.__enter__ = lambda s: s
        r.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = r

        resp = c.post(f"/api/v1/notification-channels/{slack_channel.pk}/test/")
    assert resp.status_code == 200
    data = resp.data.get("data", resp.data)
    assert data["success"] is True
