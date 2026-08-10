"""A downtime alert has to say what actually broke.

"status changed: UP → DOWN" was the whole message, so every alert sent a human
to the dashboard to find out why. The check row already holds the reason — the
HTTP code, the error text, the timing — and these tests pin that it reaches the
channel, with the people who manage the site named on it.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest

from django.utils import timezone

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.clients.models import Client
from apps.integrations.members import set_member_link
from apps.monitors.models import Monitor, MonitorCheck, NotificationChannel
from apps.monitors.notifications import (
    latest_check,
    notify_status_change,
    status_fields,
)
from apps.websites.models import Website, WebsiteAssignment

pytestmark = pytest.mark.django_db

TEAM_CHAT = "https://app.clickup.com/9001/chat/r/shared-1"


@pytest.fixture
def setup(db):
    owner = User.objects.create_user(email="detail_o@test.com", password="Pass123!")
    team = TeamService.create(name="Detail Agency", owner=owner)
    team.clickup_api_token = "pk_test"
    team.clickup_chat_url = TEAM_CHAT
    team.save()

    dev = User.objects.create_user(email="dev@detail.io", password="Pass123!")
    TeamMembership.objects.create(user=dev, team=team, role=TeamMembership.Role.DEVELOPER)
    set_member_link(team, dev, "11", "junaid")

    client_rec = Client.objects.create(team=team, name="Inspiration Ltd", assigned_to=dev)
    website = Website.objects.create(
        team=team, client=client_rec, name="Inspiration", domain="inspiration.digilatics.co",
    )
    monitor = Monitor.objects.create(
        team=team, website=website, name="Inspiration HTTP",
        monitor_type="http", url="https://inspiration.digilatics.co/",
        consecutive_failures=3,
    )
    return team, website, monitor, dev


def _failed_check(monitor):
    return MonitorCheck.objects.create(
        monitor=monitor, status="down", status_code=503,
        response_time_ms=4590, error_message="HTTP 503: Service Unavailable",
    )


# -- status_fields ---------------------------------------------------------

def test_fields_carry_the_error_the_code_and_the_timing(setup):
    _, _, monitor, _ = setup
    check = _failed_check(monitor)

    fields = dict(status_fields(monitor, "up", "down", check))

    assert fields["Error"] == "HTTP 503: Service Unavailable"
    assert fields["HTTP status"] == 503
    assert fields["Response time"] == "4590 ms"
    assert fields["Status"] == "UP → DOWN"
    assert fields["URL"] == "https://inspiration.digilatics.co/"
    assert fields["Failed checks"] == "3 in a row"
    assert fields["Checked at"]


def test_a_clean_recovery_has_no_error_or_failure_lines(setup):
    _, _, monitor, _ = setup
    monitor.consecutive_failures = 0
    check = MonitorCheck.objects.create(monitor=monitor, status="up", status_code=200, response_time_ms=3490)

    fields = dict(status_fields(monitor, "down", "up", check))

    assert "Error" not in fields
    assert "Failed checks" not in fields
    assert fields["Response time"] == "3490 ms"


def test_fields_survive_a_check_that_recorded_nothing(setup):
    """A ping/port timeout can leave every optional column empty."""
    _, _, monitor, _ = setup
    check = MonitorCheck.objects.create(monitor=monitor, status="down")

    fields = dict(status_fields(monitor, "up", "down", check))

    assert "Error" not in fields
    assert "HTTP status" not in fields
    assert fields["Status"] == "UP → DOWN"


def test_latest_check_is_the_one_that_triggered_the_alert(setup):
    _, _, monitor, _ = setup
    older = MonitorCheck.objects.create(monitor=monitor, status="up", status_code=200)
    newest = _failed_check(monitor)
    # auto_now_add stamps both rows within the same microsecond, so ordering by
    # -checked_at alone is a coin flip. Pin an explicit order to test what the
    # production flow guarantees: the row written right before the alert fires.
    MonitorCheck.objects.filter(pk=older.pk).update(
        checked_at=timezone.now() - timedelta(seconds=1)
    )
    newest.refresh_from_db()

    assert latest_check(monitor) == newest


# -- the shared channel ----------------------------------------------------

def test_the_shared_channel_message_names_client_site_error_and_manager(setup):
    _, website, monitor, _ = setup
    helper = User.objects.create_user(email="helper@detail.io", password="Pass123!")
    WebsiteAssignment.objects.create(website=website, user=helper)
    _failed_check(monitor)

    with patch("apps.integrations.clickup.ClickUpClient.post_chat") as post:
        notify_status_change(monitor, "up", "down")

    text = post.call_args.args[2]
    assert "🔴 **Inspiration Ltd** — Inspiration is DOWN" in text
    assert "Client: Inspiration Ltd" in text
    assert "Website: Inspiration (inspiration.digilatics.co)" in text
    assert "Error: HTTP 503: Service Unavailable" in text
    assert "HTTP status: 503" in text
    assert "Response time: 4590 ms" in text
    assert "Managed by: @junaid, helper@detail.io" in text
    assert post.call_args.kwargs["followers"] == ["11"]


def test_recovery_reports_the_recovered_timing(setup):
    _, _, monitor, _ = setup
    MonitorCheck.objects.create(monitor=monitor, status="up", status_code=200, response_time_ms=3490)

    with patch("apps.integrations.clickup.ClickUpClient.post_chat") as post:
        notify_status_change(monitor, "down", "up")

    text = post.call_args.args[2]
    assert "✅ **Inspiration Ltd** — Inspiration is back UP" in text
    assert "Response time: 3490 ms" in text


# -- per-website channels --------------------------------------------------

def _clickup_channel(team, chat_url):
    return NotificationChannel.objects.create(
        team=team, name="Client channel", channel_type="clickup",
        config={"api_token": "pk_site", "chat_url": chat_url},
    )


def test_a_websites_own_channel_gets_the_same_detailed_message(setup):
    team, website, monitor, _ = setup
    website.notification_channel = _clickup_channel(team, "https://app.clickup.com/9001/chat/r/site-9")
    website.save()
    monitor.refresh_from_db()
    _failed_check(monitor)

    with patch("apps.integrations.clickup.ClickUpClient.post_chat") as post:
        notify_status_change(monitor, "up", "down")

    site_call = next(c for c in post.call_args_list if c.args[1] == "site-9")
    assert "Error: HTTP 503: Service Unavailable" in site_call.args[2]
    assert "Client: Inspiration Ltd" in site_call.args[2]
    assert site_call.kwargs["followers"] == ["11"]


def test_one_channel_for_everything_posts_once(setup):
    """The website channel and the team feed pointing at the same ClickUp chat
    is the configuration we recommend — it must not double-post."""
    team, website, monitor, _ = setup
    website.notification_channel = _clickup_channel(team, TEAM_CHAT)
    website.save()
    monitor.refresh_from_db()
    _failed_check(monitor)

    with patch("apps.integrations.clickup.ClickUpClient.post_chat") as post:
        notify_status_change(monitor, "up", "down")

    assert len(post.call_args_list) == 1


def test_a_different_channel_still_gets_its_own_post(setup):
    team, website, monitor, _ = setup
    website.notification_channel = _clickup_channel(team, "https://app.clickup.com/9001/chat/r/other-2")
    website.save()
    monitor.refresh_from_db()
    _failed_check(monitor)

    with patch("apps.integrations.clickup.ClickUpClient.post_chat") as post:
        notify_status_change(monitor, "up", "down")

    assert {c.args[1] for c in post.call_args_list} == {"other-2", "shared-1"}
