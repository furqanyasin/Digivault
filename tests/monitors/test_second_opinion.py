"""Google as a second opinion when a firewall blocks our own checks."""

from unittest import mock

import pytest
from django.core.cache import cache
from django.test import override_settings

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors import second_opinion
from apps.monitors.models import Monitor, MonitorCheck
from apps.monitors.tasks import check_single_monitor, google_second_opinion

BLOCKED = {
    "status": "blocked", "response_time_ms": 90, "status_code": 202,
    "error_message": "Blocked by SiteGround (HTTP 202) — ...",
}


def _psi(status_ok=True, runtime=None):
    lr = {"audits": {"http-status-code": {"score": 1 if status_ok else 0}}}
    if runtime:
        lr["runtimeError"] = runtime
    return {"lighthouseResult": lr}


# ── parse ─────────────────────────────────────────────────────────────────────


def test_parse_loaded_page_is_up():
    assert second_opinion.parse(_psi())["status"] == "up"


@pytest.mark.parametrize("code, msg", [
    ("FAILED_DOCUMENT_REQUEST", "Lighthouse was unable to reliably load the page. (Details: net::ERR_CONNECTION_REFUSED)"),
    ("ERRORED_DOCUMENT_REQUEST", "Lighthouse was unable to reliably load the page you requested. (Status code: 503)"),
    ("DNS_FAILURE", "DNS servers could not resolve the provided domain."),
])
def test_parse_load_failure_is_down(code, msg):
    v = second_opinion.parse(_psi(runtime={"code": code, "message": msg}))
    assert v["status"] == "down"


@pytest.mark.parametrize("status", [403, 429, 401])
def test_parse_firewall_page_for_google_too_is_no_verdict(status):
    msg = f"Lighthouse was unable to reliably load the page you requested. (Status code: {status})"
    assert second_opinion.parse(_psi(runtime={"code": "ERRORED_DOCUMENT_REQUEST", "message": msg})) is None


def test_parse_garbage_is_no_verdict():
    assert second_opinion.parse({}) is None
    assert second_opinion.parse(_psi(status_ok=False)) is None


# ── wiring ────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def monitor(db):
    owner = User.objects.create_user(email="so@test.com", password="Pass123!")
    team = TeamService.create(name="SO Agency", owner=owner)
    return Monitor.objects.create(
        team=team, name="3 Wave", url="https://3wavecleaning.com", monitor_type="http",
        status="blocked", retry_count=1,
    )


@override_settings(MONITOR_SECOND_OPINION=True, PAGESPEED_API_KEY="k")
@pytest.mark.django_db
def test_blocked_check_asks_google_and_applies_up(monitor):
    with mock.patch("apps.monitors.checker.run_check", return_value=dict(BLOCKED)), \
         mock.patch.object(second_opinion, "ask_google", return_value={
             "status": "up", "status_code": 200, "message": "Up, checked by Google"}) as ask:
        check_single_monitor(str(monitor.pk))
    ask.assert_called_once_with(monitor.url)
    monitor.refresh_from_db()
    assert monitor.status == "up"
    latest = monitor.checks.order_by("-checked_at").first()
    assert (latest.status, latest.checked_via) == ("up", "google")
    # The blocked observation of our own was recorded first.
    assert monitor.checks.filter(status="blocked").count() == 1


@override_settings(MONITOR_SECOND_OPINION=True, PAGESPEED_API_KEY="k")
@pytest.mark.django_db
def test_standing_verdict_is_reused_without_asking_again(monitor):
    second_opinion.store(monitor.pk, {"status": "up", "status_code": 200, "message": "Up, checked by Google"})
    with mock.patch("apps.monitors.checker.run_check", return_value=dict(BLOCKED)), \
         mock.patch.object(second_opinion, "ask_google") as ask:
        check_single_monitor(str(monitor.pk))
    ask.assert_not_called()
    monitor.refresh_from_db()
    assert monitor.status == "up"
    assert not monitor.checks.filter(status="blocked").exists()


@override_settings(MONITOR_SECOND_OPINION=True, PAGESPEED_API_KEY="k")
@pytest.mark.django_db
def test_google_down_alerts_like_any_outage(monitor):
    with mock.patch.object(second_opinion, "ask_google", return_value={
            "status": "down", "status_code": 503, "message": "Google could not load the site either (HTTP 503)"}), \
         mock.patch("apps.monitors.tasks.notify_status_change") as notify:
        assert google_second_opinion(str(monitor.pk)) == "down"
    monitor.refresh_from_db()
    assert monitor.status == "down"
    assert monitor.is_alerting
    notify.assert_called_once()


@override_settings(MONITOR_SECOND_OPINION=True, PAGESPEED_API_KEY="k")
@pytest.mark.django_db
def test_google_down_still_answers_to_real_visitors(monitor):
    with mock.patch.object(second_opinion, "ask_google", return_value={
            "status": "down", "status_code": 503, "message": "x"}), \
         mock.patch("apps.monitors.liveness.corroborate_liveness", return_value=(True, "Visitors are being served")):
        assert google_second_opinion(str(monitor.pk)) == "blocked"
    monitor.refresh_from_db()
    assert monitor.status == "blocked"


@override_settings(MONITOR_SECOND_OPINION=True, PAGESPEED_API_KEY="k")
@pytest.mark.django_db
def test_no_verdict_leaves_it_blocked(monitor):
    with mock.patch.object(second_opinion, "ask_google", return_value=None):
        assert google_second_opinion(str(monitor.pk)) is None
    monitor.refresh_from_db()
    assert monitor.status == "blocked"
    assert not MonitorCheck.objects.filter(monitor=monitor).exists()


@override_settings(MONITOR_SECOND_OPINION=True, PAGESPEED_API_KEY="k")
@pytest.mark.django_db
def test_google_is_asked_at_most_once_per_window(monitor):
    with mock.patch("apps.monitors.tasks.google_second_opinion.delay") as delay:
        assert second_opinion.request(monitor) is True
        assert second_opinion.request(monitor) is False
    delay.assert_called_once()


@override_settings(MONITOR_SECOND_OPINION=True, PAGESPEED_API_KEY="")
def test_needs_an_api_key():
    assert second_opinion.enabled() is False
