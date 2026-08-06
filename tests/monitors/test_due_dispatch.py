"""run_due_checks must dispatch a monitor once per interval.

Beat fires every 30s but a check can take up to `timeout` seconds (30s default)
to finish. Because the completion path is what writes `last_checked_at`, a slow
or timing-out monitor was still "due" on the next beat tick and got dispatched
again — producing duplicate checks and double-counted failures.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor
from apps.monitors.tasks import run_due_checks


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@duetest.com", password="SecurePass1!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Due Team", owner=owner)


def make_monitor(team, **kwargs):
    defaults = {
        "team": team,
        "name": "Slow Site",
        "url": "https://example.com",
        "monitor_type": "http",
        "check_interval": 300,
        "status": "up",
    }
    defaults.update(kwargs)
    return Monitor.objects.create(**defaults)


@pytest.mark.django_db
def test_due_monitor_is_dispatched(team):
    monitor = make_monitor(team, last_checked_at=timezone.now() - timedelta(seconds=600))

    with patch("apps.monitors.tasks.check_single_monitor.delay") as delay:
        run_due_checks()

    delay.assert_called_once_with(str(monitor.pk))


@pytest.mark.django_db
def test_never_checked_monitor_is_dispatched(team):
    monitor = make_monitor(team, last_checked_at=None, status="pending")

    with patch("apps.monitors.tasks.check_single_monitor.delay") as delay:
        run_due_checks()

    delay.assert_called_once_with(str(monitor.pk))


@pytest.mark.django_db
def test_monitor_not_yet_due_is_skipped(team):
    make_monitor(team, last_checked_at=timezone.now() - timedelta(seconds=60))

    with patch("apps.monitors.tasks.check_single_monitor.delay") as delay:
        run_due_checks()

    delay.assert_not_called()


@pytest.mark.django_db
def test_in_flight_check_is_not_redispatched(team):
    """Second beat tick, first check still running (last_checked_at unwritten)."""
    make_monitor(team, last_checked_at=timezone.now() - timedelta(seconds=600))

    with patch("apps.monitors.tasks.check_single_monitor.delay") as delay:
        run_due_checks()
        run_due_checks()  # 30s later; the first check has not finished
        run_due_checks()

    assert delay.call_count == 1


@pytest.mark.django_db
def test_dispatch_is_capped_per_tick(team, settings):
    """A burst of simultaneous outbound requests from one IP trips WAF rate limits."""
    settings.MONITOR_MAX_CHECKS_PER_TICK = 5
    stale = timezone.now() - timedelta(seconds=6000)
    for i in range(20):
        make_monitor(team, name=f"Site {i}", url=f"https://s{i}.example.com", last_checked_at=stale)

    with patch("apps.monitors.tasks.check_single_monitor.delay") as delay:
        run_due_checks()

    assert delay.call_count == 5


@pytest.mark.django_db
def test_capped_monitors_drain_over_subsequent_ticks(team, settings):
    """Deferred monitors must not starve — later ticks pick up the remainder."""
    settings.MONITOR_MAX_CHECKS_PER_TICK = 4
    stale = timezone.now() - timedelta(seconds=6000)
    for i in range(10):
        make_monitor(team, name=f"Site {i}", url=f"https://s{i}.example.com", last_checked_at=stale)

    with patch("apps.monitors.tasks.check_single_monitor.delay") as delay:
        for _ in range(3):
            run_due_checks()
        seen = {c.args[0] for c in delay.call_args_list}

    assert len(seen) == 10  # every monitor dispatched exactly once across the ticks
    assert delay.call_count == 10


@pytest.mark.django_db
def test_oldest_checked_monitor_is_dispatched_first(team, settings):
    """Fair ordering: the most overdue monitor should not be starved by the cap."""
    now = timezone.now()
    make_monitor(team, name="Recent", url="https://recent.example.com",
                 last_checked_at=now - timedelta(seconds=1000))
    oldest = make_monitor(team, name="Oldest", url="https://oldest.example.com",
                          last_checked_at=now - timedelta(seconds=9000))

    settings.MONITOR_MAX_CHECKS_PER_TICK = 1
    with patch("apps.monitors.tasks.check_single_monitor.delay") as delay:
        run_due_checks()

    delay.assert_called_once_with(str(oldest.pk))


@pytest.mark.django_db
def test_never_checked_monitors_have_priority(team, settings):
    """A brand-new monitor should get its first check before overdue re-checks."""
    fresh = make_monitor(team, name="New", url="https://new.example.com",
                         last_checked_at=None, status="pending")
    make_monitor(team, name="Old", url="https://old.example.com",
                 last_checked_at=timezone.now() - timedelta(seconds=9000))

    settings.MONITOR_MAX_CHECKS_PER_TICK = 1
    with patch("apps.monitors.tasks.check_single_monitor.delay") as delay:
        run_due_checks()

    delay.assert_called_once_with(str(fresh.pk))


@pytest.mark.django_db
def test_default_check_interval_is_fifteen_minutes(team):
    """Frequent polling from one IP is what gets the monitor blocked."""
    monitor = make_monitor(team)
    del monitor  # created with an explicit interval; assert the model default

    assert Monitor._meta.get_field("check_interval").default == 900


@pytest.mark.django_db
def test_paused_and_inactive_monitors_are_skipped(team):
    stale = timezone.now() - timedelta(seconds=600)
    make_monitor(team, name="Paused", status="paused", last_checked_at=stale)
    make_monitor(team, name="Inactive", is_active=False, last_checked_at=stale)

    with patch("apps.monitors.tasks.check_single_monitor.delay") as delay:
        run_due_checks()

    delay.assert_not_called()
