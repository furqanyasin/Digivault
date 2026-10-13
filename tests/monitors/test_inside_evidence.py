"""A blocked monitor is settled by evidence our IP never fetches.

SiteGround's anti-bot challenges our monitoring IP itself, so every vendor that
hits it asks for a support ticket per hosting account. The site reporting in
(WP Connect heartbeat) and its real visitors (tracking snippet) are outbound
from the site's side, and no firewall in front of it can stop them.
"""

from unittest import mock

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors import evidence, second_opinion
from apps.monitors.models import Monitor
from apps.monitors.tasks import check_single_monitor
from apps.websites.models import Website

BLOCKED = {
    "status": "blocked", "response_time_ms": 90, "status_code": 202,
    "error_message": "Blocked by SiteGround (HTTP 202) — ...",
}
DOWN = {"status": "down", "response_time_ms": None, "status_code": None, "error_message": "timed out"}


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="ev@test.com", password="Pass123!")
    team = TeamService.create(name="Evidence Agency", owner=owner)
    return Website.objects.create(team=team, name="3 Wave", domain="3wavecleaning.com")


@pytest.fixture
def monitor(website):
    m = Monitor.objects.filter(website=website).first() or Monitor.objects.create(
        team=website.team, name="3 Wave", url="https://3wavecleaning.com", website=website,
    )
    Monitor.objects.filter(pk=m.pk).update(status="blocked", retry_count=1)
    m.refresh_from_db()
    return m


def _ago(seconds):
    return timezone.now() - timezone.timedelta(seconds=seconds)


def _heartbeat(website, ack_ago, loopback=None, loopback_ago=None, ms=120):
    Website.objects.filter(pk=website.pk).update(
        wp_connect_last_ack=_ago(ack_ago),
        wp_connect_loopback_status=loopback,
        wp_connect_loopback_ms=ms if loopback else None,
        wp_connect_loopback_at=_ago(loopback_ago if loopback_ago is not None else ack_ago),
    )


def _check(monitor, result=BLOCKED, attempt=1):
    with mock.patch("apps.monitors.checker.run_check", return_value=dict(result)), \
         mock.patch.object(second_opinion, "request") as ask, \
         mock.patch("apps.monitors.tasks.notify_status_change") as notify:
        check_single_monitor(str(monitor.pk), attempt)
    monitor.refresh_from_db()
    return monitor.checks.order_by("-checked_at").first(), ask, notify


# ── the rule (pure) ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_nothing_fresh_is_no_verdict(monitor, website):
    _heartbeat(website, ack_ago=3600, loopback=200)
    Website.objects.filter(pk=website.pk).update(snippet_last_seen_at=_ago(3600))
    monitor.refresh_from_db()
    assert evidence.inside_view(monitor) is None


@pytest.mark.django_db
def test_stale_loopback_does_not_speak_for_a_fresh_heartbeat(monitor, website):
    # An old 500 must not keep calling a site down after the loopback stopped.
    _heartbeat(website, ack_ago=30, loopback=500, loopback_ago=7200)
    monitor.refresh_from_db()
    verdict = evidence.inside_view(monitor)
    assert verdict["status"] == "up"
    assert verdict["status_code"] is None


# ── wiring ────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_site_heartbeat_settles_a_blocked_check_as_up(monitor, website):
    _heartbeat(website, ack_ago=60, loopback=200)
    latest, ask, _ = _check(monitor)
    assert monitor.status == "up"
    assert (latest.status, latest.checked_via, latest.status_code) == ("up", "site", 200)
    ask.assert_not_called()  # no Google quota spent on a site that vouched for itself
    assert monitor.uptime_24h == 100


@pytest.mark.django_db
def test_site_loopback_server_error_is_a_real_outage(monitor, website):
    _heartbeat(website, ack_ago=60, loopback=500)
    latest, _, notify = _check(monitor)
    assert monitor.status == "down"
    assert (latest.status, latest.checked_via) == ("down", "site")
    assert monitor.is_alerting
    notify.assert_called_once()


@pytest.mark.django_db
def test_real_visitors_settle_a_blocked_check_as_up(monitor, website):
    Website.objects.filter(pk=website.pk).update(snippet_last_seen_at=_ago(120))
    latest, ask, _ = _check(monitor)
    assert monitor.status == "up"
    assert (latest.status, latest.checked_via) == ("up", "visitors")
    ask.assert_not_called()


@pytest.mark.django_db
def test_no_inside_evidence_falls_back_to_google(monitor):
    latest, ask, _ = _check(monitor)
    assert monitor.status == "blocked"
    assert latest.checked_via == ""
    ask.assert_called_once()


@pytest.mark.django_db
def test_a_failed_probe_is_not_called_up_by_an_old_visit(monitor, website):
    """Our own request timed out three times: liveness may downgrade it to
    blocked, but a visit minutes ago must not turn it into "up"."""
    Website.objects.filter(pk=website.pk).update(snippet_last_seen_at=_ago(120))
    latest, _, _ = _check(monitor, result=DOWN, attempt=3)
    assert monitor.status == "blocked"
    assert latest.checked_via == ""
