"""Making a blocked monitor fixable: our IP named everywhere, and one fix per
firewall that covers every site it blocks."""

from unittest import mock

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.common import outbound
from apps.monitors.checker import _block_message
from apps.monitors.models import Monitor, MonitorCheck

PW = "Pass123!"


@pytest.fixture(autouse=True)
def _no_cached_ip():
    from django.core.cache import cache

    cache.delete(outbound._EGRESS_CACHE_KEY)
    yield
    cache.delete(outbound._EGRESS_CACHE_KEY)


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="mb_owner@test.com", password=PW)


@pytest.fixture
def team(owner):
    return TeamService.create(name="MB Agency", owner=owner)


def _client(user):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": user.email, "password": PW}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


def _blocked(team, name, url, vendor="SiteGround", runs=2):
    m = Monitor.objects.create(team=team, name=name, url=url, monitor_type="http", status="blocked")
    for _ in range(runs):
        MonitorCheck.objects.create(
            monitor=m, status="blocked", status_code=202, error_message=_block_message(vendor, 202)
        )
    return m


# ── egress IP ─────────────────────────────────────────────────────────────────


@override_settings(MONITOR_EGRESS_IPS=["203.0.113.7"])
def test_configured_ip_wins():
    assert outbound.egress_ips() == ["203.0.113.7"]


@override_settings(MONITOR_EGRESS_IPS=[], MONITOR_DETECT_EGRESS_IP=True)
def test_detected_when_unset_and_cached():
    resp = mock.MagicMock()
    resp.read.return_value = b"8.8.4.4\n"
    resp.__enter__.return_value = resp
    with mock.patch.object(outbound.urllib.request, "urlopen", return_value=resp) as urlopen:
        assert outbound.egress_ips() == ["8.8.4.4"]
        assert outbound.egress_ips() == ["8.8.4.4"]
    assert urlopen.call_count == 1  # cached


@override_settings(MONITOR_EGRESS_IPS=[], MONITOR_DETECT_EGRESS_IP=True)
def test_detection_failure_is_empty_not_an_error():
    with mock.patch.object(outbound.urllib.request, "urlopen", side_effect=OSError("offline")):
        assert outbound.egress_ips() == []


@override_settings(MONITOR_EGRESS_IPS=["203.0.113.7"])
def test_block_message_names_the_ip_and_is_not_cut_off():
    msg = _block_message("SiteGround", 202)
    assert "203.0.113.7" in msg
    assert msg.endswith("https://stacksmonitor.com/bot")


@override_settings(MONITOR_EGRESS_IPS=["203.0.113.7"])
@pytest.mark.django_db
def test_monitoring_info_lists_the_ip():
    data = APIClient().get("/api/v1/monitoring-info/").data
    assert data["egress_ips"] == ["203.0.113.7"]
    assert "203.0.113.7" in data["allowlist"]["siteground"]


# ── block info / summary ──────────────────────────────────────────────────────


@override_settings(MONITOR_EGRESS_IPS=["203.0.113.7"])
@pytest.mark.django_db
def test_block_count_comes_from_the_checks(owner, team):
    m = _blocked(team, "3 Wave", "https://3wavecleaning.com", runs=3)
    assert m.consecutive_blocks == 0  # the counter the card used to read
    info = _client(owner).get(f"/api/v1/monitors/{m.pk}/").data["block_info"]
    assert info["consecutive_blocks"] == 3
    assert info["vendor"] == "SiteGround"


@override_settings(MONITOR_EGRESS_IPS=["203.0.113.7"])
@pytest.mark.django_db
def test_summary_gives_one_ticket_for_every_siteground_site(owner, team):
    _blocked(team, "3 Wave", "https://3wavecleaning.com")
    _blocked(team, "Acme", "https://www.acme.io/")
    _blocked(team, "CF site", "https://cf.example", vendor="Cloudflare")
    Monitor.objects.create(team=team, name="Up", url="https://ok.example", monitor_type="http", status="up")

    data = _client(owner).get("/api/v1/monitors/blocked-summary/").data
    assert data["egress_ips"] == ["203.0.113.7"]
    groups = {g["vendor"]: g for g in data["groups"]}
    assert set(groups) == {"SiteGround", "Cloudflare"}

    sg = groups["SiteGround"]
    assert sg["count"] == 2
    ticket = sg["fix"]["text"]
    assert "203.0.113.7" in ticket
    assert "- 3wavecleaning.com" in ticket and "- acme.io" in ticket
    assert "StacksMonitor-Bot" in ticket

    cf = groups["Cloudflare"]["fix"]["text"]
    assert 'http.user_agent contains "StacksMonitor-Bot"' in cf and "203.0.113.7" in cf


@pytest.mark.django_db
def test_summary_is_team_scoped(owner, team):
    other = TeamService.create(name="Other", owner=User.objects.create_user(email="o@mb.io", password=PW))
    _blocked(other, "Theirs", "https://theirs.example")
    assert _client(owner).get("/api/v1/monitors/blocked-summary/").data["groups"] == []
