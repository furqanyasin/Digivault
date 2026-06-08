"""Phase 0.5 — dead-man's-switch heartbeat task."""

from unittest.mock import patch

from django.test import override_settings

from apps.common.tasks import system_heartbeat


@override_settings(HEARTBEAT_PING_URL="")
def test_heartbeat_noop_when_unconfigured():
    assert system_heartbeat() is False


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc")
def test_heartbeat_pings_when_configured():
    with patch("apps.common.tasks.urllib.request.urlopen") as mock_open:
        assert system_heartbeat() is True
        mock_open.assert_called_once()


@override_settings(HEARTBEAT_PING_URL="https://hc-ping.com/abc")
def test_heartbeat_returns_false_on_failure():
    with patch(
        "apps.common.tasks.urllib.request.urlopen", side_effect=OSError("network")
    ):
        assert system_heartbeat() is False
