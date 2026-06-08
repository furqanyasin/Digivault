"""Phase 4.4 — WebSocket token extraction (header/subprotocol over query string)."""

from apps.alerts.consumers import AlertConsumer


def test_subprotocol_token_preferred():
    scope = {
        "subprotocols": ["bearer", "tok123"],
        "headers": [],
        "query_string": b"token=fromquery",
    }
    token, sub = AlertConsumer._extract_token(scope)
    assert token == "tok123"
    assert sub == "bearer"


def test_authorization_header():
    scope = {
        "subprotocols": [],
        "headers": [(b"authorization", b"Bearer hdrtoken")],
        "query_string": b"token=fromquery",
    }
    token, sub = AlertConsumer._extract_token(scope)
    assert token == "hdrtoken"
    assert sub is None


def test_query_string_fallback():
    scope = {"subprotocols": [], "headers": [], "query_string": b"token=legacy"}
    token, sub = AlertConsumer._extract_token(scope)
    assert token == "legacy"
    assert sub is None


def test_no_token():
    scope = {"subprotocols": [], "headers": [], "query_string": b""}
    token, sub = AlertConsumer._extract_token(scope)
    assert token is None
    assert sub is None
