"""ClickUp delivery routing — Chat channel (v3) vs task comment (v2).

Routing lives in post_clickup; the HTTP call itself now goes through
ClickUpClient, so these patch the client's transport rather than urllib.
The assertions are unchanged: same URLs, same auth header, same return value.
"""

import pytest

from apps.monitors.notifications import parse_clickup_chat, post_clickup


class _FakeResp:
    status_code = 200
    text = ""

    def json(self):
        return {}


class _RecordingSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "json": json})
        return _FakeResp()


@pytest.fixture
def session(monkeypatch):
    """Swap the transport ClickUpClient defaults to."""
    rec = _RecordingSession()
    monkeypatch.setattr("apps.integrations.clickup.requests", rec)
    return rec


def test_parse_clickup_chat_link():
    ws, ch = parse_clickup_chat("https://acme.clickup.com/25658037/chat/r/rf0nn-49438")
    assert ws == "25658037"
    assert ch == "rf0nn-49438"
    assert parse_clickup_chat("") == (None, None)
    assert parse_clickup_chat("https://example.com/x") == (None, None)


def test_post_clickup_returns_false_without_target(session):
    assert post_clickup({"api_token": "pk_1"}, "hi") is False
    assert post_clickup({}, "hi") is False
    assert session.calls == []


def test_post_clickup_uses_chat_v3(session):
    ok = post_clickup(
        {"api_token": "pk_1", "chat_url": "https://x.clickup.com/123/chat/r/abc-1", "task_id": "ignored"},
        "hello",
    )
    assert ok is True
    assert session.calls[-1]["url"] == (
        "https://api.clickup.com/api/v3/workspaces/123/chat/channels/abc-1/messages"
    )
    assert session.calls[-1]["headers"]["Authorization"] == "pk_1"


def test_post_clickup_falls_back_to_task_comment(session):
    ok = post_clickup({"api_token": "pk_1", "task_id": "86evnnba3"}, "hello")
    assert ok is True
    assert session.calls[-1]["url"] == "https://api.clickup.com/api/v2/task/86evnnba3/comment"
    assert session.calls[-1]["json"] == {"comment_text": "hello"}
