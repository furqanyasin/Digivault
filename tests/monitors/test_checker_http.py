"""check_http result classification.

Covers the three ways a reachable site was being misreported as a hard outage:
bot-challenge responses, a non-2xx `expected_status_code` that could never
match, and transport errors collapsed into an unactionable message.
"""

import socket
import ssl
import urllib.error
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest

from apps.monitors.checker import check_http

URL = "https://example.com"


def headers(**kwargs):
    m = Message()
    for k, v in kwargs.items():
        m[k.replace("_", "-")] = v
    return m


def http_error(code, **hdrs):
    return urllib.error.HTTPError(
        URL, code, f"HTTP Error {code}", headers(**hdrs), None
    )


def ok_response(status=200, body=b"hello world"):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda s, *a: False
    return resp


# --- bot challenges -------------------------------------------------------


def test_cloudflare_challenge_is_not_reported_as_down():
    err = http_error(403, cf_mitigated="challenge", server="cloudflare")
    with patch("urllib.request.urlopen", side_effect=err):
        result = check_http(URL)

    assert result["status"] == "degraded"
    assert result["status_code"] == 403
    assert "cloudflare" in result["error_message"].lower()
    assert "allowlist" in result["error_message"].lower()


def test_cloudflare_403_without_mitigation_header_is_still_a_challenge():
    with patch("urllib.request.urlopen", side_effect=http_error(403, server="cloudflare")):
        result = check_http(URL)

    assert result["status"] == "degraded"


def test_plain_server_403_is_still_down():
    """A 403 from an ordinary origin is a real misconfiguration, not a challenge."""
    with patch("urllib.request.urlopen", side_effect=http_error(403, server="nginx")):
        result = check_http(URL)

    assert result["status"] == "down"
    assert result["status_code"] == 403


def test_cloudflare_522_stays_down():
    """522 means Cloudflare could not reach the origin — a genuine outage."""
    with patch("urllib.request.urlopen", side_effect=http_error(522, server="cloudflare")):
        result = check_http(URL)

    assert result["status"] == "down"
    assert result["status_code"] == 522
    assert "origin server timed out" in result["error_message"]
    assert "<none>" not in result["error_message"]


# --- expected_status honoured for non-2xx ---------------------------------


def test_expected_non_2xx_status_reports_up():
    with patch("urllib.request.urlopen", side_effect=http_error(403, server="cloudflare")):
        result = check_http(URL, expected_status=403)

    assert result["status"] == "up"
    assert result["status_code"] == 403


def test_expected_401_reports_up():
    with patch("urllib.request.urlopen", side_effect=http_error(401, server="nginx")):
        result = check_http(URL, expected_status=401)

    assert result["status"] == "up"


def test_unexpected_5xx_is_down():
    with patch("urllib.request.urlopen", side_effect=http_error(500, server="nginx")):
        result = check_http(URL)

    assert result["status"] == "down"
    assert result["status_code"] == 500


# --- transport error classification ---------------------------------------


@pytest.mark.parametrize(
    "reason,expected_fragment",
    [
        (socket.timeout("timed out"), "timed out after 30s"),
        (ssl.SSLError("SSLV3_ALERT_HANDSHAKE_FAILURE"), "tls handshake failed"),
        (socket.gaierror("Name or service not known"), "dns lookup failed"),
        (ConnectionRefusedError("refused"), "connection refused"),
    ],
)
def test_transport_errors_get_actionable_messages(reason, expected_fragment):
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(reason)):
        result = check_http(URL, timeout=30)

    assert result["status"] == "down"
    assert result["status_code"] is None
    assert expected_fragment in result["error_message"].lower()


# --- unchanged happy paths ------------------------------------------------


def test_matching_status_is_up():
    with patch("urllib.request.urlopen", return_value=ok_response()):
        result = check_http(URL)

    assert result["status"] == "up"
    assert result["response_time_ms"] is not None


def test_missing_keyword_is_down():
    with patch("urllib.request.urlopen", return_value=ok_response()):
        result = check_http(URL, keyword="nope")

    assert result["status"] == "down"
    assert "nope" in result["error_message"]


def test_unexpected_2xx_is_degraded():
    with patch("urllib.request.urlopen", return_value=ok_response(status=204)):
        result = check_http(URL, expected_status=200)

    assert result["status"] == "degraded"
