"""A site served on only one of example.com and www.example.com is not down.

lamberthomeinspections.com was the live case. Cloudflare holds a certificate for
the www name only, so a handshake for the apex gets alert 40
(SSLV3_ALERT_HANDSHAKE_FAILURE). Every visitor arrives on www and never
notices, but the monitor was given the apex and reported an outage until
someone edited the URL by hand. Every server-side fetch now tries the twin, and
the monitor adopts the name that answered.
"""

import io
import socket
import ssl
import urllib.error
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.common import outbound
from apps.monitors import checker
from apps.monitors.checker import check_http
from apps.monitors.models import Monitor
from apps.monitors.tasks import check_single_monitor


@pytest.fixture(autouse=True)
def _no_ssrf_or_backoff(monkeypatch):
    monkeypatch.setattr(outbound, "assert_public_url", lambda url: None)
    cache.clear()
    yield
    cache.clear()


def handshake_failure():
    return urllib.error.URLError(
        ssl.SSLError(1, "[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] ssl/tls alert handshake failure")
    )


def ok_response(status=200):
    resp = MagicMock()
    resp.status = status
    resp.getcode.return_value = status
    resp.read.return_value = b"hello world"
    resp.headers = Message()
    resp.geturl.return_value = "https://www.example.com/"
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda s, *a: False
    return resp


def serving_only(served_host, answer=None):
    """An opener that answers for `served_host` and fails the handshake elsewhere."""
    calls = []

    def _open(req, timeout=None):
        calls.append(req.full_url)
        if req.host == served_host:
            if isinstance(answer, Exception):
                raise answer
            return answer or ok_response()
        raise handshake_failure()

    fake = MagicMock()
    fake.open = _open
    return patch.object(outbound, "_opener", lambda: fake), calls


# --- the twin rule ----------------------------------------------------------


@pytest.mark.parametrize(
    "url,twin",
    [
        ("https://example.com", "https://www.example.com"),
        ("https://www.example.com/path?q=1", "https://example.com/path?q=1"),
        ("https://example.co.uk/", "https://www.example.co.uk/"),
        ("http://example.com:8080/", "http://www.example.com:8080/"),
        ("https://shop.example.com", None),
        ("https://www.shop.example.com", None),
        ("https://10.0.0.1", None),
    ],
)
def test_sibling_url(url, twin):
    assert outbound.sibling_url(url) == twin


# --- outbound.fetch ---------------------------------------------------------


def test_fetch_answers_on_www_when_apex_has_no_certificate():
    ctx, calls = serving_only("www.example.com")
    with ctx:
        result = outbound.fetch("https://example.com/", bypass_budget=True)

    assert result.status_code == 200
    assert result.host_fallback is True
    assert calls == ["https://example.com/", "https://www.example.com/"]


def test_fetch_answers_on_apex_when_www_has_no_dns():
    ctx, _ = serving_only("example.com")
    with ctx, patch.object(outbound, "_open", wraps=outbound._open) as spy:
        spy.side_effect = [
            urllib.error.URLError(socket.gaierror(-2, "Name or service not known")),
            outbound.FetchResult(200, "ok", {}, 10, "https://example.com/"),
        ]
        result = outbound.fetch("https://www.example.com/", bypass_budget=True)

    assert result.host_fallback is True


def test_fetch_reraises_the_original_error_when_both_names_fail():
    ctx, calls = serving_only("nobody.example.net")
    with ctx, pytest.raises(urllib.error.URLError) as info:
        outbound.fetch("https://example.com/", bypass_budget=True)

    assert "SSLV3_ALERT_HANDSHAKE_FAILURE" in str(info.value.reason)
    assert len(calls) == 2


def test_a_timeout_is_not_retried_on_the_twin():
    """A timeout says nothing about the name, and retrying doubles the wait."""
    ctx, calls = serving_only("www.example.com")
    with ctx, patch.object(outbound, "_open") as spy:
        spy.side_effect = urllib.error.URLError(TimeoutError("timed out"))
        with pytest.raises(urllib.error.URLError):
            outbound.fetch("https://example.com/", bypass_budget=True)

    assert spy.call_count == 1


def test_a_post_is_never_replayed_to_the_twin():
    ctx, calls = serving_only("www.example.com")
    with ctx, pytest.raises(urllib.error.URLError):
        outbound.fetch("https://example.com/", method="POST", data=b"{}",
                       bypass_budget=True)

    assert calls == ["https://example.com/"]


def test_a_subdomain_has_no_twin_to_try():
    ctx, calls = serving_only("www.shop.example.com")
    with ctx, pytest.raises(urllib.error.URLError):
        outbound.fetch("https://shop.example.com/", bypass_budget=True)

    assert calls == ["https://shop.example.com/"]


# --- check_http / check_ssl -------------------------------------------------


def test_check_http_reports_up_and_hands_back_the_working_url():
    ctx, _ = serving_only("www.example.com")
    with ctx:
        result = check_http("https://example.com")

    assert result["status"] == "up"
    assert result["resolved_url"] == "https://www.example.com"


def test_check_http_without_fallback_carries_no_resolved_url():
    ctx, _ = serving_only("example.com")
    with ctx:
        result = check_http("https://example.com")

    assert result["status"] == "up"
    assert "resolved_url" not in result


def test_check_ssl_falls_back_to_the_twins_certificate():
    good = {"status": "up", "response_time_ms": 12, "status_code": None, "error_message": ""}
    bad = {"status": "down", "response_time_ms": None, "status_code": None,
           "error_message": "SSL error: handshake failure", "name_failure": True}

    with patch.object(checker, "_check_ssl", side_effect=[bad, good]) as inner:
        result = checker.check_ssl("example.com")

    assert result["status"] == "up"
    assert result["resolved_url"] == "www.example.com"
    assert inner.call_args_list[1].args[0] == "www.example.com"


def test_check_ssl_expiry_is_not_excused_by_the_twin():
    expiring = {"status": "down", "response_time_ms": 12, "status_code": None,
                "error_message": "SSL expires in 3 days"}
    with patch.object(checker, "_check_ssl", return_value=expiring) as inner:
        result = checker.check_ssl("example.com")

    assert result["error_message"] == "SSL expires in 3 days"
    assert inner.call_count == 1


# --- the monitor adopts the name that answered ------------------------------


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="owner@twin.com", password="SecurePass1!")
    return TeamService.create(name="Twin Team", owner=owner)


@pytest.fixture
def monitor(team):
    return Monitor.objects.create(
        team=team, name="Twin", url="https://example.com",
        monitor_type="http", status="down", retry_count=1,
    )


UP_ON_WWW = {"status": "up", "response_time_ms": 80, "status_code": 200,
             "error_message": "", "resolved_url": "https://www.example.com"}


@pytest.mark.django_db
def test_monitor_adopts_the_www_url(monitor):
    with patch("apps.monitors.checker.run_check", return_value=UP_ON_WWW):
        check_single_monitor(str(monitor.pk))

    monitor.refresh_from_db()
    assert monitor.url == "https://www.example.com"
    assert monitor.status == "up"


@pytest.mark.django_db
def test_monitor_keeps_its_url_when_the_team_already_monitors_the_twin(monitor, team):
    Monitor.objects.create(team=team, name="Twin www", url="https://www.example.com",
                           monitor_type="http")
    with patch("apps.monitors.checker.run_check", return_value=UP_ON_WWW):
        check_single_monitor(str(monitor.pk))

    monitor.refresh_from_db()
    assert monitor.url == "https://example.com"
    assert monitor.status == "up"
