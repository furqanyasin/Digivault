"""`blocked` is a status of its own — a WAF stopping us is not the site being down."""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor, MonitorCheck
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@blocked.com", password="SecurePass1!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Blocked Team", owner=owner)


@pytest.fixture
def monitor(team):
    return Monitor.objects.create(
        team=team,
        name="Blocked Site",
        url="https://example.com",
        monitor_type="http",
        status="up",
    )


@pytest.mark.django_db
def test_blocked_is_a_declared_status():
    assert Monitor.Status.BLOCKED == "blocked"
    assert MonitorCheck.Status.BLOCKED == "blocked"


@pytest.mark.django_db
def test_monitor_tracks_consecutive_blocks(monitor):
    assert monitor.consecutive_blocks == 0


@pytest.mark.django_db
def test_blocked_checks_excluded_from_uptime_denominator(monitor):
    """A period we could not observe is not a period of downtime.

    Counting a block as down invents an outage; counting it as up invents
    health. The only honest thing is to leave it out of the ratio entirely.
    """
    for _ in range(2):
        MonitorCheck.objects.create(monitor=monitor, status="up", response_time_ms=100)
    MonitorCheck.objects.create(monitor=monitor, status="blocked")

    monitor.recalculate_uptime()
    monitor.refresh_from_db()

    assert monitor.uptime_24h == 100.0


@pytest.mark.django_db
def test_blocked_does_not_mask_real_downtime(monitor):
    MonitorCheck.objects.create(monitor=monitor, status="up", response_time_ms=100)
    MonitorCheck.objects.create(monitor=monitor, status="down")
    MonitorCheck.objects.create(monitor=monitor, status="blocked")

    monitor.recalculate_uptime()
    monitor.refresh_from_db()

    # 1 up of 2 observable checks. The blocked one is simply absent.
    assert monitor.uptime_24h == 50.0


@pytest.mark.django_db
def test_all_blocked_gives_null_uptime(monitor):
    for _ in range(3):
        MonitorCheck.objects.create(monitor=monitor, status="blocked")

    monitor.recalculate_uptime()
    monitor.refresh_from_db()

    assert monitor.uptime_24h is None


@pytest.mark.django_db
def test_blocked_monitor_warns_but_is_not_critical(team):
    """Being unable to see a site is worth flagging, not worth paging about."""
    website = Website.objects.create(team=team, name="Blocked", domain="blocked.test")
    Monitor.objects.filter(website=website).update(status=Monitor.Status.BLOCKED)

    website.recalculate_health_score()
    website.refresh_from_db()

    assert website.health_score < 100
    assert website.health_score >= 90
    assert website.status != Website.Status.CRITICAL


@pytest.mark.django_db
def test_down_monitor_is_still_critical(team):
    """The blocked branch must not have softened a genuine outage."""
    website = Website.objects.create(team=team, name="Down", domain="down.test")
    Monitor.objects.filter(website=website).update(status=Monitor.Status.DOWN)

    website.recalculate_health_score()
    website.refresh_from_db()

    assert website.status == Website.Status.CRITICAL
