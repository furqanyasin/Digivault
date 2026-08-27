"""`outbound.fetch` must say when it only read part of a response.

The default 64 KB cap is fine for the block-page sniffing the monitor does, but
an Elementor page's builder tree runs far past it. A silently truncated body
parses as broken JSON, which a caller cannot tell apart from a page that simply
has no form — so the cap has to be observable.
"""

import io

import pytest

from apps.common import outbound


class _Resp(io.BytesIO):
    status = 200

    def __init__(self, payload):
        super().__init__(payload)
        self.headers = {}

    def geturl(self):
        return "https://truncation.test/wp-json/wp/v2/pages"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _no_budget(monkeypatch):
    """Take DNS, Redis and the per-host bucket out of the picture.

    The SSRF guard is exercised in its own tests; here it would only fail on the
    fake hostname never resolving.
    """
    monkeypatch.setattr(outbound, "assert_public_url", lambda url: None)
    monkeypatch.setattr(outbound, "cooldown_remaining", lambda host: 0)
    monkeypatch.setattr(outbound, "consume_budget", lambda host: True)
    monkeypatch.setattr(outbound, "_record_outcome", lambda host, result: None)


def _serve(monkeypatch, payload):
    opener = type("O", (), {"open": lambda self, req, timeout: _Resp(payload)})()
    monkeypatch.setattr(outbound, "_opener", lambda: opener)


def test_a_body_past_the_cap_is_reported_as_truncated(monkeypatch):
    _serve(monkeypatch, b"x" * 101)

    result = outbound.fetch("https://truncation.test/a", read_bytes=100)

    assert result.truncated is True
    assert len(result.body) == 100


def test_a_body_exactly_at_the_cap_is_not_truncated(monkeypatch):
    _serve(monkeypatch, b"x" * 100)

    result = outbound.fetch("https://truncation.test/a", read_bytes=100)

    assert result.truncated is False
    assert len(result.body) == 100


def test_a_body_under_the_cap_is_not_truncated(monkeypatch):
    _serve(monkeypatch, b"x" * 50)

    result = outbound.fetch("https://truncation.test/a", read_bytes=100)

    assert result.truncated is False
    assert result.body == "x" * 50
