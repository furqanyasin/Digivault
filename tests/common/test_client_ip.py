"""The client address is resolved once, by uvicorn, and nothing re-parses it.

With ``--forwarded-allow-ips='*'`` uvicorn took the leftmost X-Forwarded-For
entry, the three app helpers took the leftmost entry again, and DRF keyed its
anonymous throttles on the raw header. nginx appends to whatever the client
sent, so the client chose all three: a spoofed IP in every audit row and a fresh
rate-limit bucket per request. These tests pin the compose value, run uvicorn's
own middleware with it, and check the app reads only the resolved address.
"""

import re
from pathlib import Path

import pytest
from django.test import RequestFactory
from rest_framework.request import Request
from rest_framework.throttling import AnonRateThrottle
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from apps.common.client_ip import client_ip

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ["docker-compose.production.cloudpanel.yml", "docker-compose.production.yml"]
FLAG = re.compile(r"--forwarded-allow-ips='\$\{FORWARDED_ALLOW_IPS:-([^}]*)\}'")


def _trusted_values():
    values = []
    for name in COMPOSE_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "--forwarded-allow-ips='*'" not in text, f"{name} trusts every proxy again"
        values += FLAG.findall(text)
    return values


def test_every_uvicorn_service_trusts_the_same_private_ranges():
    values = _trusted_values()
    # api + api-ingest in the CloudPanel file, api in the other one.
    assert len(values) == 3
    assert len(set(values)) == 1


TRUSTED = _trusted_values()[0]


async def _resolve(peer: str, forwarded: str | None) -> str:
    seen = {}

    async def app(scope, receive, send):
        seen["client"] = scope["client"][0]

    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    scope = {"type": "http", "scheme": "http", "client": (peer, 51000), "headers": headers}
    await ProxyHeadersMiddleware(app, trusted_hosts=TRUSTED)(scope, None, None)
    return seen["client"]


@pytest.mark.parametrize("bridge", ["172.18.0.1", "172.31.0.1", "192.168.16.1", "10.0.0.2", "127.0.0.1"])
async def test_nginx_appended_address_wins_over_a_client_written_one(bridge):
    # The client sent "X-Forwarded-For: 1.2.3.4"; nginx appended the real peer.
    assert await _resolve(bridge, "1.2.3.4, 203.0.113.9") == "203.0.113.9"


async def test_header_is_ignored_from_an_untrusted_peer():
    # Something reaching uvicorn directly from the internet cannot pick its IP.
    assert await _resolve("198.51.100.7", "1.2.3.4") == "198.51.100.7"


async def test_no_header_leaves_the_peer():
    assert await _resolve("172.18.0.1", None) == "172.18.0.1"


# ── The app reads only the resolved address ────────────────────────────────


def _request(**meta):
    return RequestFactory().get("/", **meta)


def test_client_ip_ignores_x_forwarded_for():
    req = _request(REMOTE_ADDR="203.0.113.9", HTTP_X_FORWARDED_FOR="1.2.3.4")
    assert client_ip(req) == "203.0.113.9"


def test_audit_and_auth_helpers_use_the_resolved_address():
    from apps.accounts.totp_views import _get_ip as totp_ip
    from apps.audit.services import _get_ip as audit_ip
    from apps.credentials.views import _get_client_ip as vault_ip

    req = _request(REMOTE_ADDR="203.0.113.9", HTTP_X_FORWARDED_FOR="1.2.3.4")
    assert totp_ip(req) == audit_ip(req) == vault_ip(req) == "203.0.113.9"


def test_anon_throttle_key_cannot_be_changed_by_the_client():
    # A new X-Forwarded-For per request used to mean a new bucket per request.
    throttle = AnonRateThrottle()
    idents = {
        throttle.get_ident(Request(_request(REMOTE_ADDR="203.0.113.9", HTTP_X_FORWARDED_FOR=f"10.9.8.{n}")))
        for n in range(5)
    }
    assert idents == {"203.0.113.9"}
