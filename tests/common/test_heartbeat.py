"""Phase 0.5 — dead-man's-switch heartbeat task."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.common.tasks import system_heartbeat
from apps.monitors.models import Monitor

pytestmark = pytest.mark.django_db

PING = "apps.common.tasks.urllib.request.urlopen"


class FakeBroker:
    """Stands in for the Celery broker's Redis: LLEN per list key."""

    def __init__(self):
        self.lengths = {}

    def llen(self, key):
        return self.lengths.get(key, 0)


@pytest.fixture(autouse=True)
def broker():
    fake = FakeBroker()
    with patch("apps.common.tasks._broker_client", return_value=fake):
        yield fake


def _monitor(team, *, last_checked_ago=None, created_ago=None, interval=900, **kw):
    m = Monitor.objects.create(
        team=team,
        name=kw.pop("name", "Site"),
        url="https://site.example",
        check_interval=interval,
        **kw,
    )
    now = timezone.now()
    fields = {}
    if last_checked_ago is not None:
        fields["last_checked_at"] = now - last_checked_ago
    if created_ago is not None:
        fields["created_at"] = now - created_ago
    if fields:
        Monitor.objects.filter(pk=m.pk).update(**fields)
    return m


@override_settings(HEARTBEAT_PING_URL="")
def test_heartbeat_noop_when_unconfigured():
    assert system_heartbeat() is False


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc")
def test_heartbeat_pings_when_configured():
    with patch(PING) as mock_open:
        assert system_heartbeat() is True
        mock_open.assert_called_once()


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc")
def test_heartbeat_returns_false_on_failure():
    with patch(PING, side_effect=OSError("network")):
        assert system_heartbeat() is False


# ── Withheld while uptime checks have stopped ──────────────────────────────
#
# The heartbeat runs on the default queue (the ingest worker), so on its own it
# kept pinging while the monitors worker was down and nothing was being checked.


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc")
def test_heartbeat_pings_when_monitors_are_on_schedule(team):
    # Checked 14 minutes ago on a 15-minute interval: due in a minute.
    _monitor(team, last_checked_ago=timedelta(minutes=14))
    with patch(PING) as mock_open:
        assert system_heartbeat() is True
        mock_open.assert_called_once()


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc")
def test_heartbeat_tolerates_quiet_fleet_on_long_intervals(team):
    # Nothing checked for ten minutes is normal on the default 15-minute
    # interval — a "check in the last N minutes" rule would page for it.
    _monitor(team, name="A", last_checked_ago=timedelta(minutes=10))
    _monitor(team, name="B", last_checked_ago=timedelta(minutes=12))
    with patch(PING) as mock_open:
        assert system_heartbeat() is True
        mock_open.assert_called_once()


@override_settings(
    HEARTBEAT_PING_URL="https://hc-ping.com/abc", HEARTBEAT_MONITOR_GRACE_SECONDS=300
)
def test_heartbeat_withheld_when_a_monitor_is_overdue(team):
    # Due 6 minutes ago, past the 5-minute grace: checks have stopped.
    _monitor(team, last_checked_ago=timedelta(minutes=21))
    with patch(PING) as mock_open:
        assert system_heartbeat() is False
        mock_open.assert_not_called()


@override_settings(
    HEARTBEAT_PING_URL="https://hc-ping.com/abc", HEARTBEAT_MONITOR_GRACE_SECONDS=300
)
def test_heartbeat_withheld_for_never_checked_old_monitor(team):
    _monitor(team, created_ago=timedelta(minutes=10))
    with patch(PING) as mock_open:
        assert system_heartbeat() is False
        mock_open.assert_not_called()


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc")
def test_heartbeat_ignores_brand_new_unchecked_monitor(team):
    _monitor(team)  # created just now, not yet picked up by a tick
    with patch(PING) as mock_open:
        assert system_heartbeat() is True
        mock_open.assert_called_once()


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc")
def test_heartbeat_ignores_paused_and_inactive_monitors(team):
    long_ago = timedelta(days=2)
    _monitor(team, name="Paused", status=Monitor.Status.PAUSED, last_checked_ago=long_ago)
    _monitor(team, name="Off", is_active=False, last_checked_ago=long_ago)
    with patch(PING) as mock_open:
        assert system_heartbeat() is True
        mock_open.assert_called_once()


# ── Withheld while a queue is backed up ────────────────────────────────────
#
# Workers alive and answering pings, Postgres fine, ingest an hour behind: the
# failure every other check reports as healthy.

LIMITS = {"ingest": 5000, "monitors": 200, "slow": 500, "celery": 1000}


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc", HEARTBEAT_QUEUE_LIMITS=LIMITS)
def test_heartbeat_pings_with_normal_queue_depths(broker):
    broker.lengths = {"ingest": 4999, "monitors": 3, "slow": 40}
    with patch(PING) as mock_open:
        assert system_heartbeat() is True
        mock_open.assert_called_once()


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc", HEARTBEAT_QUEUE_LIMITS=LIMITS)
def test_heartbeat_withheld_when_a_queue_is_backed_up(broker):
    broker.lengths = {"monitors": 201}
    with patch(PING) as mock_open:
        assert system_heartbeat() is False
        mock_open.assert_not_called()


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc", HEARTBEAT_QUEUE_LIMITS=LIMITS)
def test_heartbeat_counts_priority_lists_toward_the_backlog(broker):
    # Kombu stores prioritised messages in `<queue>\x06\x16<step>` lists; a
    # backlog split across them is still one backlog.
    broker.lengths = {"ingest": 3000, "ingest\x06\x163": 1500, "ingest\x06\x169": 600}
    with patch(PING) as mock_open:
        assert system_heartbeat() is False
        mock_open.assert_not_called()


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc")
def test_heartbeat_withheld_when_broker_cannot_answer():
    class DeadBroker:
        def llen(self, key):
            raise ConnectionError("broker down")

    with patch("apps.common.tasks._broker_client", return_value=DeadBroker()), patch(PING) as mock_open:
        with pytest.raises(ConnectionError):
            system_heartbeat()
        mock_open.assert_not_called()


def test_queue_limits_setting_parses_env_override(monkeypatch):
    import environ

    env = environ.Env()
    monkeypatch.setenv("HEARTBEAT_QUEUE_LIMITS", "ingest=10;monitors=2")
    parsed = env.dict("HEARTBEAT_QUEUE_LIMITS", cast={"value": int}, default={})
    assert parsed == {"ingest": 10, "monitors": 2}
