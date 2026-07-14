"""Uptime alerts route to the website's dedicated uptime channel when set,
falling back to the general website channel otherwise."""

from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor, NotificationChannel
from apps.monitors.notifications import notify_status_change
from apps.websites.models import Website

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="uptch_o@test.com", password="Pass123!")
    return TeamService.create(name="UptCh Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="UptCh Site", domain="uptch.io")


@pytest.fixture
def monitor(team, website):
    return Monitor.objects.create(
        team=team, website=website, name="UptCh HTTP",
        monitor_type="http", url="https://uptch.io",
    )


def _channel(team, name):
    return NotificationChannel.objects.create(
        team=team, name=name, channel_type="slack",
        config={"url": "https://hooks.slack.com/services/x"},
    )


def _fire(monitor):
    with patch("apps.monitors.notifications.dispatch") as mock_dispatch:
        notify_status_change(monitor, "up", "down")
    return [call.args[0] for call in mock_dispatch.call_args_list]


def test_uptime_channel_preferred_over_general(team, website, monitor):
    general = _channel(team, "General")
    uptime = _channel(team, "Uptime only")
    website.notification_channel = general
    website.uptime_notification_channel = uptime
    website.save()
    monitor.refresh_from_db()

    sent_to = _fire(monitor)
    assert [c.id for c in sent_to] == [uptime.id]


def test_falls_back_to_general_channel(team, website, monitor):
    general = _channel(team, "General")
    website.notification_channel = general
    website.save()
    monitor.refresh_from_db()

    sent_to = _fire(monitor)
    assert [c.id for c in sent_to] == [general.id]


def test_no_channels_no_dispatch(monitor):
    assert _fire(monitor) == []
