"""Real visitors outrank our probe.

The platform already records `website.last_seen_at` on every ingest, and ingest
arrives from a real browser loading the client's page. If our single-IP probe
cannot reach a site that was serving people ninety seconds ago, the site is up
and we are the ones being blocked.
"""

from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.liveness import corroborate_liveness
from apps.monitors.models import Monitor, MonitorCheck
from apps.monitors.tasks import check_single_monitor
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@live.com", password="SecurePass1!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Live Team", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Live", domain="live.test")


@pytest.fixture
def monitor(team, website):
    m = Monitor.objects.filter(website=website).first() or Monitor.objects.create(
        team=team, name="Live", url="https://live.test", website=website,
    )
    # Auto-provisioned monitors start `pending`, and the existing contract
    # deliberately stays silent on a monitor's very first result. These tests are
    # about the second result onward, so give it an established `up` baseline.
    Monitor.objects.filter(pk=m.pk).update(status="up", retry_count=1)
    m.refresh_from_db()
    return m


def _seen(website, seconds_ago):
    Website.objects.filter(pk=website.pk).update(
        last_seen_at=timezone.now() - timezone.timedelta(seconds=seconds_ago)
    )


DOWN = {"status": "down", "response_time_ms": None, "status_code": 403, "error_message": "HTTP 403"}
UP = {"status": "up", "response_time_ms": 90, "status_code": 200, "error_message": ""}


# ── the rule ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_fresh_last_seen_corroborates(monitor, website):
    _seen(website, 60)
    monitor.refresh_from_db()
    suppress, reason = corroborate_liveness(monitor)
    assert suppress is True
    assert "visitor" in reason.lower() or "browser" in reason.lower()


@pytest.mark.django_db
def test_stale_last_seen_does_not_corroborate(monitor, website):
    _seen(website, 3600)
    monitor.refresh_from_db()
    suppress, _ = corroborate_liveness(monitor)
    assert suppress is False


@pytest.mark.django_db
def test_website_never_seen_does_not_corroborate(monitor, website):
    Website.objects.filter(pk=website.pk).update(last_seen_at=None)
    monitor.refresh_from_db()
    assert corroborate_liveness(monitor)[0] is False


@pytest.mark.django_db
def test_monitor_without_website_does_not_corroborate(team):
    standalone = Monitor.objects.create(
        team=team, name="Standalone", url="https://nope.test",
    )
    assert corroborate_liveness(standalone)[0] is False


@pytest.mark.django_db
def test_suppression_cap_stops_corroborating(monitor, website):
    """A permanently blocked monitor must not go permanently silent."""
    _seen(website, 60)
    Monitor.objects.filter(pk=monitor.pk).update(consecutive_blocks=99)
    monitor.refresh_from_db()
    assert corroborate_liveness(monitor)[0] is False


@pytest.mark.django_db
def test_exception_falls_through_to_alerting(monitor, website):
    """Failing toward alerting is the safe direction."""
    _seen(website, 60)
    monitor.refresh_from_db()
    with patch("apps.monitors.liveness._window_seconds", side_effect=RuntimeError("boom")):
        assert corroborate_liveness(monitor)[0] is False


# ── wired into the task ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_confirmed_down_is_recorded_as_blocked_when_visitors_are_being_served(
    monitor, website
):
    _seen(website, 60)

    with patch("apps.monitors.checker.run_check", return_value=DOWN), \
         patch("apps.monitors.tasks.notify_status_change") as notify:
        check_single_monitor(str(monitor.pk), attempt=3)

    assert MonitorCheck.objects.filter(monitor=monitor, status="blocked").count() == 1
    assert MonitorCheck.objects.filter(monitor=monitor, status="down").count() == 0
    monitor.refresh_from_db()
    assert monitor.status == "blocked"
    assert monitor.consecutive_failures == 0
    notify.assert_not_called()


@pytest.mark.django_db
def test_confirmed_down_alerts_when_no_visitors_corroborate(monitor, website):
    _seen(website, 7200)

    with patch("apps.monitors.checker.run_check", return_value=DOWN), \
         patch("apps.monitors.tasks.notify_status_change") as notify:
        check_single_monitor(str(monitor.pk), attempt=3)

    monitor.refresh_from_db()
    assert monitor.status == "down"
    assert monitor.consecutive_failures == 1
    notify.assert_called_once()


@pytest.mark.django_db
def test_corroboration_never_reports_up(monitor, website):
    """It may only ever suppress. It must not be able to invent uptime."""
    _seen(website, 30)

    with patch("apps.monitors.checker.run_check", return_value=DOWN), \
         patch("apps.monitors.tasks.notify_status_change"):
        check_single_monitor(str(monitor.pk), attempt=3)

    monitor.refresh_from_db()
    assert monitor.status != "up"
    assert not MonitorCheck.objects.filter(monitor=monitor, status="up").exists()


@pytest.mark.django_db
def test_suppression_eventually_gives_way_to_the_alert(monitor, website, settings):
    """After the cap, the down alert fires anyway with the corroboration noted."""
    settings.LIVENESS_MAX_SUPPRESSED_CHECKS = 2
    _seen(website, 30)

    with patch("apps.monitors.checker.run_check", return_value=DOWN), \
         patch("apps.monitors.tasks.notify_status_change") as notify:
        for _ in range(3):
            _seen(website, 30)
            check_single_monitor(str(monitor.pk), attempt=3)

    monitor.refresh_from_db()
    assert monitor.status == "down"
    notify.assert_called_once()


@pytest.mark.django_db
def test_recovery_resets_the_suppression_counter(monitor, website):
    _seen(website, 30)

    with patch("apps.monitors.checker.run_check", return_value=DOWN), \
         patch("apps.monitors.tasks.notify_status_change"):
        check_single_monitor(str(monitor.pk), attempt=3)

    monitor.refresh_from_db()
    assert monitor.consecutive_blocks == 1

    with patch("apps.monitors.checker.run_check", return_value=UP), \
         patch("apps.monitors.tasks.notify_status_change"):
        check_single_monitor(str(monitor.pk))

    monitor.refresh_from_db()
    assert monitor.consecutive_blocks == 0
    assert monitor.status == "up"
