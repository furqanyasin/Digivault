"""The allowlist surface — who we are, so a client can let us through.

Being blocked is fixable in about thirty seconds, but only if the agency can
find our identity. UptimeRobot publishes its IPs and user-agent for exactly this
reason; without an equivalent, "monitoring blocked" is a dead end.
"""

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.common import outbound
from apps.monitors.models import Monitor, MonitorCheck
from apps.monitors.serializers import MonitorSerializer


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="owner@info.com", password="SecurePass1!")
    return TeamService.create(name="Info Team", owner=owner)


@pytest.fixture
def monitor(team):
    return Monitor.objects.create(
        team=team, name="Info", url="https://info.test", status="up",
    )


@pytest.mark.django_db
def test_monitoring_info_is_public(client):
    """A site owner debugging their firewall is not logged into Digivault."""
    resp = client.get(reverse("monitoring-info"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_monitoring_info_publishes_the_identity(client, settings):
    settings.MONITOR_EGRESS_IPS = ["203.0.113.10"]
    body = client.get(reverse("monitoring-info")).json()["data"]

    assert body["user_agent"] == outbound.USER_AGENT
    assert body["egress_ips"] == ["203.0.113.10"]
    for vendor in ("cloudflare", "wordfence", "sucuri", "htaccess"):
        assert body["allowlist"][vendor]


@pytest.mark.django_db
def test_allowlist_rules_carry_the_real_ip(client, settings):
    settings.MONITOR_EGRESS_IPS = ["203.0.113.10"]
    body = client.get(reverse("monitoring-info")).json()["data"]
    assert "203.0.113.10" in body["allowlist"]["htaccess"]


@pytest.mark.django_db
def test_block_info_absent_when_monitor_is_healthy(monitor):
    MonitorCheck.objects.create(monitor=monitor, status="up", response_time_ms=10)
    assert MonitorSerializer(monitor).data["block_info"] is None


@pytest.mark.django_db
def test_block_info_present_when_latest_check_was_blocked(monitor):
    Monitor.objects.filter(pk=monitor.pk).update(status="blocked")
    MonitorCheck.objects.create(
        monitor=monitor, status="blocked", error_message="Blocked by Wordfence",
    )
    monitor.refresh_from_db()

    info = MonitorSerializer(monitor).data["block_info"]
    assert info is not None
    assert "Wordfence" in info["message"]
    assert info["help_url"].endswith("/bot")
    assert info["since"] is not None
