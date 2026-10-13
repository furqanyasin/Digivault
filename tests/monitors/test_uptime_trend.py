"""Team-wide daily uptime trend — backs the dashboard's uptime sparkline."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.monitors.models import Monitor, MonitorCheck

URL = "/api/v1/monitors/uptime-trend/"


def _monitor(team, name="m", website=None):
    return Monitor.objects.create(
        team=team, website=website, name=name, url=f"https://{name}.example",
        status=Monitor.Status.UP,
    )


def _check(monitor, status, days_ago=0):
    check = MonitorCheck.objects.create(monitor=monitor, status=status)
    # checked_at is auto_now_add, so it has to be moved after insert.
    MonitorCheck.objects.filter(pk=check.pk).update(
        checked_at=timezone.now() - timedelta(days=days_ago)
    )
    return check


@pytest.mark.django_db
class TestUptimeTrend:
    def test_requires_auth(self, client):
        assert client.get(URL).status_code == 401

    def test_returns_one_point_per_day(self, auth_client, team):
        resp = auth_client.get(f"{URL}?days=7")
        assert resp.status_code == 200
        assert resp.data["days"] == 7
        assert len(resp.data["points"]) == 7

    def test_days_are_consecutive_and_end_today(self, auth_client, team):
        resp = auth_client.get(f"{URL}?days=5")
        dates = [p["date"] for p in resp.data["points"]]
        assert dates == sorted(dates)
        assert dates[-1] == timezone.localdate().isoformat()

    def test_all_up_is_100(self, auth_client, team):
        m = _monitor(team)
        for _ in range(4):
            _check(m, MonitorCheck.Status.UP, days_ago=1)
        resp = auth_client.get(f"{URL}?days=3")
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        point = next(p for p in resp.data["points"] if p["date"] == yesterday)
        assert point["value"] == 100.0

    def test_half_down_is_50(self, auth_client, team):
        m = _monitor(team)
        _check(m, MonitorCheck.Status.UP, days_ago=1)
        _check(m, MonitorCheck.Status.DOWN, days_ago=1)
        resp = auth_client.get(f"{URL}?days=3")
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        point = next(p for p in resp.data["points"] if p["date"] == yesterday)
        assert point["value"] == 50.0

    def test_day_with_no_checks_is_null_not_zero(self, auth_client, team):
        """No checks means we were blind, not that the site was down.

        Emitting 0 would draw a crash into the sparkline that never happened;
        emitting 100 would invent uptime we never observed.
        """
        m = _monitor(team)
        _check(m, MonitorCheck.Status.UP, days_ago=0)
        resp = auth_client.get(f"{URL}?days=3")
        older = (timezone.localdate() - timedelta(days=2)).isoformat()
        point = next(p for p in resp.data["points"] if p["date"] == older)
        assert point["value"] is None

    def test_degraded_counts_against_uptime(self, auth_client, team):
        m = _monitor(team)
        _check(m, MonitorCheck.Status.UP, days_ago=0)
        _check(m, MonitorCheck.Status.DEGRADED, days_ago=0)
        resp = auth_client.get(f"{URL}?days=1")
        assert resp.data["points"][0]["value"] == 50.0

    def test_blocked_is_excluded_from_both_sides(self, auth_client, team):
        """A WAF answering is not downtime — same rule as recalculate_uptime."""
        m = _monitor(team)
        _check(m, MonitorCheck.Status.UP, days_ago=0)
        _check(m, MonitorCheck.Status.BLOCKED, days_ago=0)
        _check(m, MonitorCheck.Status.BLOCKED, days_ago=0)
        point = auth_client.get(f"{URL}?days=1").data["points"][0]
        assert point["value"] == 100.0
        assert (point["up"], point["total"]) == (1, 1)

    def test_only_blocked_is_null(self, auth_client, team):
        _check(_monitor(team), MonitorCheck.Status.BLOCKED, days_ago=0)
        point = auth_client.get(f"{URL}?days=1").data["points"][0]
        assert point["value"] is None
        assert point["total"] == 0

    def test_points_carry_counts_for_pooling(self, auth_client, team):
        m = _monitor(team)
        _check(m, MonitorCheck.Status.UP, days_ago=0)
        _check(m, MonitorCheck.Status.UP, days_ago=0)
        _check(m, MonitorCheck.Status.DOWN, days_ago=0)
        point = auth_client.get(f"{URL}?days=1").data["points"][0]
        assert (point["up"], point["total"]) == (2, 3)

    def test_averages_across_all_team_monitors(self, auth_client, team):
        a, b = _monitor(team, "a"), _monitor(team, "b")
        _check(a, MonitorCheck.Status.UP, days_ago=0)
        _check(b, MonitorCheck.Status.DOWN, days_ago=0)
        resp = auth_client.get(f"{URL}?days=1")
        assert resp.data["points"][0]["value"] == 50.0

    def test_other_teams_checks_are_excluded(self, auth_client, team, django_user_model):
        from apps.accounts.services import TeamService

        outsider = django_user_model.objects.create_user(
            email="outsider-trend@test.com", password="Pass123!"
        )
        other_team = TeamService.create(name="Other", owner=outsider)
        _check(_monitor(other_team, "theirs"), MonitorCheck.Status.DOWN, days_ago=0)

        mine = _monitor(team, "mine")
        _check(mine, MonitorCheck.Status.UP, days_ago=0)

        resp = auth_client.get(f"{URL}?days=1")
        assert resp.data["points"][0]["value"] == 100.0

    def test_checks_outside_the_window_are_excluded(self, auth_client, team):
        m = _monitor(team)
        _check(m, MonitorCheck.Status.DOWN, days_ago=30)
        resp = auth_client.get(f"{URL}?days=3")
        assert all(p["value"] is None for p in resp.data["points"])

    @pytest.mark.parametrize("requested,expected", [("0", 1), ("-5", 1), ("999", 90), ("abc", 14)])
    def test_days_param_is_clamped(self, auth_client, team, requested, expected):
        resp = auth_client.get(f"{URL}?days={requested}")
        assert resp.status_code == 200
        assert resp.data["days"] == expected


@pytest.mark.django_db
class TestUptimeTrendDateRange:
    """`from`/`to` back the dashboard's Flatpickr range picker."""

    def test_explicit_range_wins_over_days(self, auth_client, team):
        resp = auth_client.get(f"{URL}?days=14&from=2026-07-01&to=2026-07-05")
        assert resp.status_code == 200
        dates = [p["date"] for p in resp.data["points"]]
        assert dates == [
            "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05",
        ]
        assert resp.data["days"] == 5

    def test_single_day_range(self, auth_client, team):
        resp = auth_client.get(f"{URL}?from=2026-07-03&to=2026-07-03")
        assert [p["date"] for p in resp.data["points"]] == ["2026-07-03"]

    def test_reversed_range_is_normalised(self, auth_client, team):
        """A picker can hand back the two dates in either order."""
        resp = auth_client.get(f"{URL}?from=2026-07-05&to=2026-07-01")
        dates = [p["date"] for p in resp.data["points"]]
        assert dates[0] == "2026-07-01" and dates[-1] == "2026-07-05"

    def test_range_longer_than_max_is_truncated_from_the_end(self, auth_client, team):
        resp = auth_client.get(f"{URL}?from=2020-01-01&to=2026-07-05")
        assert resp.data["days"] == 90
        assert resp.data["points"][-1]["date"] == "2026-07-05"

    def test_garbage_dates_fall_back_to_days(self, auth_client, team):
        resp = auth_client.get(f"{URL}?from=not-a-date&to=also-bad&days=5")
        assert resp.status_code == 200
        assert resp.data["days"] == 5
        assert resp.data["points"][-1]["date"] == timezone.localdate().isoformat()

    def test_only_from_falls_back_to_days(self, auth_client, team):
        """Half a range is not a range."""
        resp = auth_client.get(f"{URL}?from=2026-07-01&days=3")
        assert resp.data["days"] == 3
        assert resp.data["points"][-1]["date"] == timezone.localdate().isoformat()

    def test_checks_inside_an_explicit_range_are_counted(self, auth_client, team):
        m = _monitor(team)
        _check(m, MonitorCheck.Status.DOWN, days_ago=3)
        today = timezone.localdate()
        start = (today - timedelta(days=5)).isoformat()
        resp = auth_client.get(f"{URL}?from={start}&to={today.isoformat()}")
        target = (today - timedelta(days=3)).isoformat()
        point = next(p for p in resp.data["points"] if p["date"] == target)
        assert point["value"] == 0.0
