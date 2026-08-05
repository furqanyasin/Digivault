"""Uptime status changes announce themselves in the team ClickUp channel.

This is independent of the per-website NotificationChannel routing — a team with
no channels configured still gets the chat post, and vice versa.
"""
from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor
from apps.monitors.notifications import notify_status_change
from apps.websites.models import Website


@pytest.fixture
def monitor(db):
    owner = User.objects.create_user(email="upowner@x.io", password="Pass123!")
    team = TeamService.create(name="Uptime Co", owner=owner)
    team.clickup_chat_url = "https://app.clickup.com/9001/chat/r/chan-77"
    team.clickup_api_token = "pk_test"
    team.save()
    website = Website.objects.create(team=team, name="Example", domain="example.com")
    return Monitor.objects.create(
        team=team, website=website, name="Example",
        url="https://example.com", monitor_type="http",
    )


def test_going_down_announces_the_problem(monitor):
    with patch("apps.integrations.chat.notify_problem") as np:
        notify_status_change(monitor, "up", "down")

    assert np.called
    kwargs = np.call_args.kwargs
    assert kwargs["subject"] == f"monitor:{monitor.id}:down"
    assert "DOWN" in kwargs["title"]


def test_recovering_announces_the_recovery_with_the_same_subject(monitor):
    with patch("apps.integrations.chat.notify_recovery") as nr:
        notify_status_change(monitor, "down", "up")

    assert nr.called
    assert nr.call_args.kwargs["subject"] == f"monitor:{monitor.id}:down"


def test_degraded_announces_a_problem(monitor):
    with patch("apps.integrations.chat.notify_problem") as np:
        notify_status_change(monitor, "up", "degraded")

    assert np.called


def test_an_uninteresting_transition_announces_nothing(monitor):
    with patch("apps.integrations.chat.notify_problem") as np, \
         patch("apps.integrations.chat.notify_recovery") as nr:
        notify_status_change(monitor, "pending", "up")

    assert not np.called
    assert not nr.called


def test_a_monitor_with_no_website_announces_nothing(monitor):
    monitor.website = None
    monitor.save()

    with patch("apps.integrations.chat.notify_problem") as np:
        notify_status_change(monitor, "up", "down")

    assert not np.called
