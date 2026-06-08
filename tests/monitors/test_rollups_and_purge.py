"""Phase 0.1 — uptime rollups + raw-check retention."""

import datetime

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor, MonitorCheck, MonitorUptimeRollup


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@rollup.com", password="SecurePass1!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Rollup Team", owner=owner)


@pytest.fixture
def monitor(team):
    return Monitor.objects.create(
        team=team,
        name="Rollup Site",
        url="https://example.com",
        monitor_type="http",
        status="up",
    )


def _make_check(monitor, status, when, response_time_ms=None):
    """Create a check then force checked_at (bypasses auto_now_add via .update)."""
    check = MonitorCheck.objects.create(
        monitor=monitor,
        status=status,
        response_time_ms=response_time_ms,
    )
    MonitorCheck.objects.filter(pk=check.pk).update(checked_at=when)
    return check


@pytest.mark.django_db
def test_rollup_aggregates_a_day_of_mixed_checks(monitor):
    from apps.monitors.tasks import rollup_daily_uptime

    day = timezone.now() - datetime.timedelta(days=1)
    midday = day.replace(hour=12, minute=0, second=0, microsecond=0)
    target = midday.date()

    # 6 up, 2 degraded, 2 down = 10 total; uptime (up+degraded)/total = 80%
    for _ in range(6):
        _make_check(monitor, "up", midday, response_time_ms=100)
    for _ in range(2):
        _make_check(monitor, "degraded", midday, response_time_ms=300)
    for _ in range(2):
        _make_check(monitor, "down", midday)

    rollup_daily_uptime(target_date=target.isoformat())

    rollup = MonitorUptimeRollup.objects.get(monitor=monitor, date=target)
    assert rollup.checks_total == 10
    assert rollup.checks_up == 6
    assert rollup.checks_degraded == 2
    # uptime counts up only (down + degraded are not "up")
    assert rollup.uptime_pct == 60.0
    # avg response time over checks that recorded one: (6*100 + 2*300)/8 = 150
    assert rollup.avg_response_time_ms == 150.0


@pytest.mark.django_db
def test_rollup_is_idempotent(monitor):
    from apps.monitors.tasks import rollup_daily_uptime

    day = (timezone.now() - datetime.timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    target = day.date()
    _make_check(monitor, "up", day, response_time_ms=120)
    _make_check(monitor, "down", day)

    rollup_daily_uptime(target_date=target.isoformat())
    rollup_daily_uptime(target_date=target.isoformat())

    rollups = MonitorUptimeRollup.objects.filter(monitor=monitor, date=target)
    assert rollups.count() == 1
    assert rollups.first().uptime_pct == 50.0


@pytest.mark.django_db
def test_rollup_defaults_to_yesterday(monitor):
    from apps.monitors.tasks import rollup_daily_uptime

    yesterday = timezone.now() - datetime.timedelta(days=1)
    _make_check(monitor, "up", yesterday.replace(hour=9), response_time_ms=80)

    rollup_daily_uptime()

    assert MonitorUptimeRollup.objects.filter(
        monitor=monitor, date=yesterday.date()
    ).exists()


@pytest.mark.django_db
def test_purge_deletes_old_checks_keeps_recent(monitor):
    from apps.monitors.tasks import purge_old_checks

    now = timezone.now()
    old = _make_check(monitor, "up", now - datetime.timedelta(days=40))
    recent = _make_check(monitor, "up", now - datetime.timedelta(days=2))

    removed = purge_old_checks(days=35)

    assert removed == 1
    assert not MonitorCheck.objects.filter(pk=old.pk).exists()
    assert MonitorCheck.objects.filter(pk=recent.pk).exists()
