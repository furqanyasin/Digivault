"""ClickUp delivery routing — Chat channel (v3) vs task comment (v2)."""

import urllib.request

from apps.monitors.notifications import parse_clickup_chat, post_clickup


class _FakeResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_parse_clickup_chat_link():
    ws, ch = parse_clickup_chat("https://digilatics.clickup.com/25658037/chat/r/rf0nn-49438")
    assert ws == "25658037"
    assert ch == "rf0nn-49438"
    assert parse_clickup_chat("") == (None, None)
    assert parse_clickup_chat("https://example.com/x") == (None, None)


def test_post_clickup_returns_false_without_target():
    assert post_clickup({"api_token": "pk_1"}, "hi") is False
    assert post_clickup({}, "hi") is False


def test_post_clickup_uses_chat_v3(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=10):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    ok = post_clickup(
        {"api_token": "pk_1", "chat_url": "https://x.clickup.com/123/chat/r/abc-1", "task_id": "ignored"},
        "hello",
    )
    assert ok is True
    assert seen["url"] == "https://api.clickup.com/api/v3/workspaces/123/chat/channels/abc-1/messages"
    assert seen["auth"] == "pk_1"


def test_post_clickup_falls_back_to_task_comment(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=10):
        seen["url"] = req.full_url
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    ok = post_clickup({"api_token": "pk_1", "task_id": "86evnnba3"}, "hello")
    assert ok is True
    assert seen["url"] == "https://api.clickup.com/api/v2/task/86evnnba3/comment"
