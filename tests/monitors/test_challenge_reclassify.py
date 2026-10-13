"""A SiteGround 202 challenge is `blocked`, end to end and in the history."""

import importlib
from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.common import outbound
from apps.monitors.checker import _classify_http
from apps.monitors.models import Monitor, MonitorCheck, MonitorUptimeRollup

SG = {"server": "nginx", "host-header": "8441280b0c35cbc1147f8ba998a563a7"}


def test_challenge_classifies_as_blocked_with_the_way_out():
    result = outbound.FetchResult(202, "", SG, 170, "https://blackland.example/")
    outcome = _classify_http(result, 200, "")

    assert outcome["status"] == "blocked"
    assert "SiteGround" in outcome["error_message"]
    assert "support" in outcome["error_message"]
    assert "expected status" not in outcome["error_message"]


@pytest.mark.django_db
def test_migration_rewrites_history_and_uptime(db):
    owner = User.objects.create_user(email="sg_o@test.com", password="Pass123!")
    team = TeamService.create(name="SG Agency", owner=owner)
    monitor = Monitor.objects.create(
        team=team, name="Blackland", url="https://blackland.example",
        status="degraded", uptime_24h=0.0, uptime_7d=0.0, uptime_30d=0.0,
    )
    now = timezone.now()
    for minutes in (15, 30, 45):
        MonitorCheck.objects.create(
            monitor=monitor, status="degraded", status_code=202,
            response_time_ms=170, error_message="Got 202, expected 200",
            checked_at=now - timedelta(minutes=minutes),
        )
    # A genuinely degraded check on another monitor must be left alone.
    other = Monitor.objects.create(team=team, name="Other", url="https://other.example",
                                   status="degraded")
    MonitorCheck.objects.create(monitor=other, status="degraded", status_code=301,
                                error_message="Got 301, expected 200")
    MonitorUptimeRollup.objects.create(
        monitor=monitor, date=(now - timedelta(minutes=15)).date(),
        checks_total=3, checks_up=0, checks_degraded=3, uptime_pct=0.0,
    )

    importlib.import_module(
        "apps.monitors.migrations.0012_reclassify_challenge_202_as_blocked"
    ).forwards(django_apps, None)

    monitor.refresh_from_db()
    assert monitor.status == "blocked"
    assert set(monitor.checks.values_list("status", flat=True)) == {"blocked"}
    assert (monitor.uptime_24h, monitor.uptime_7d, monitor.uptime_30d) == (None, None, None)
    assert not MonitorUptimeRollup.objects.filter(monitor=monitor).exists()
    assert other.checks.get().status == "degraded"
    other.refresh_from_db()
    assert other.status == "degraded"
