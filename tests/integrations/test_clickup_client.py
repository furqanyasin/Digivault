"""ClickUpClient — the single place Digivault talks to the ClickUp REST API.

Five modules used to build their own urllib requests with hand-rolled auth and
error handling. These tests pin the behaviour that replaces them: correct URL,
method, auth header and body, and a typed error on any non-2xx.

The HTTP boundary is the one thing mocked here — it is a third-party API, so
there is nothing real to call. Everything else is the actual client.
"""
import json

import pytest

from apps.integrations.clickup import ClickUpClient, ClickUpError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


class RecordingSession:
    """Captures the outgoing request instead of sending it."""

    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.calls = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "headers": headers or {}, "json": json, "timeout": timeout}
        )
        return self.response

    @property
    def last(self):
        return self.calls[-1]


def test_create_task_posts_to_the_list_endpoint_and_returns_the_task():
    session = RecordingSession(FakeResponse(200, {"id": "abc123", "url": "https://app.clickup.com/t/abc123"}))
    client = ClickUpClient("pk_test_token", session=session)

    task = client.create_task("list-9", name="Site down: example.com", description="body text")

    assert task["id"] == "abc123"
    assert session.last["method"] == "POST"
    assert session.last["url"] == "https://api.clickup.com/api/v2/list/list-9/task"
    assert session.last["json"]["name"] == "Site down: example.com"
    assert session.last["json"]["description"] == "body text"


def test_create_task_sends_assignees_and_tags_only_when_given():
    session = RecordingSession(FakeResponse(200, {"id": "t1"}))
    client = ClickUpClient("pk_test_token", session=session)

    client.create_task("list-9", name="No extras")
    assert "assignees" not in session.last["json"]
    assert "tags" not in session.last["json"]

    client.create_task("list-9", name="With extras", assignees=[7, 8], tags=["digivault"])
    assert session.last["json"]["assignees"] == [7, 8]
    assert session.last["json"]["tags"] == ["digivault"]


def test_every_request_carries_the_token_as_the_authorization_header():
    session = RecordingSession()
    client = ClickUpClient("pk_secret", session=session)

    client.whoami()

    assert session.last["headers"]["Authorization"] == "pk_secret"
    assert session.last["url"] == "https://api.clickup.com/api/v2/user"


def test_comment_posts_comment_text_to_the_task():
    session = RecordingSession(FakeResponse(200, {"id": "c1"}))
    client = ClickUpClient("pk_test_token", session=session)

    client.comment("task-5", "SSL expires in 7 days")

    assert session.last["url"] == "https://api.clickup.com/api/v2/task/task-5/comment"
    assert session.last["json"] == {"comment_text": "SSL expires in 7 days"}


def test_chat_message_uses_the_v3_workspace_endpoint():
    session = RecordingSession(FakeResponse(201, {"id": "m1"}))
    client = ClickUpClient("pk_test_token", session=session)

    client.post_chat("2565", "rf0nn-49438", "monitor recovered")

    assert session.last["url"] == (
        "https://api.clickup.com/api/v3/workspaces/2565/chat/channels/rf0nn-49438/messages"
    )
    assert session.last["json"]["content"] == "monitor recovered"


def test_non_2xx_raises_clickup_error_carrying_the_status():
    session = RecordingSession(FakeResponse(401, {"err": "Token invalid"}, text="Token invalid"))
    client = ClickUpClient("bad_token", session=session)

    with pytest.raises(ClickUpError) as exc:
        client.whoami()

    assert exc.value.status_code == 401
    assert "401" in str(exc.value)


def test_a_client_without_a_token_refuses_to_call_out():
    client = ClickUpClient("", session=RecordingSession())

    with pytest.raises(ClickUpError):
        client.whoami()


# ---------------------------------------------------------------------------
# Chat link parsing — lives here rather than in monitors because integrations,
# domains and site_health all need it now.
# ---------------------------------------------------------------------------

def test_parse_clickup_chat_lives_on_the_clickup_module():
    from apps.integrations.clickup import parse_clickup_chat

    ws, ch = parse_clickup_chat("https://digilatics.clickup.com/25658037/chat/r/rf0nn-49438")
    assert (ws, ch) == ("25658037", "rf0nn-49438")
    assert parse_clickup_chat("") == (None, None)
    assert parse_clickup_chat("https://example.com/x") == (None, None)


def test_a_synthesized_channel_url_parses_back():
    """create_chat_channel builds its URL by hand; it must round-trip."""
    from apps.integrations.clickup import parse_clickup_chat

    assert parse_clickup_chat("https://app.clickup.com/9001/chat/r/chan-77") == ("9001", "chan-77")


def test_monitors_still_re_exports_parse_clickup_chat():
    from apps.integrations.clickup import parse_clickup_chat as from_integrations
    from apps.monitors.notifications import parse_clickup_chat as from_monitors

    assert from_monitors is from_integrations


# ---------------------------------------------------------------------------
# Workspaces, channel creation, message followers
# ---------------------------------------------------------------------------

def test_workspaces_reads_the_v2_team_endpoint():
    session = RecordingSession(
        FakeResponse(200, {"teams": [{"id": "9001", "name": "Digilatics", "members": []}]})
    )
    client = ClickUpClient("pk_test", session=session)

    teams = client.workspaces()

    assert session.last["url"] == "https://api.clickup.com/api/v2/team"
    assert teams[0]["id"] == "9001"


def test_workspaces_returns_empty_when_clickup_sends_no_teams_key():
    session = RecordingSession(FakeResponse(200, {}))

    assert ClickUpClient("pk_test", session=session).workspaces() == []


def test_create_chat_channel_posts_name_and_user_ids():
    session = RecordingSession(FakeResponse(200, {"id": "chan-77"}))
    client = ClickUpClient("pk_test", session=session)

    channel = client.create_chat_channel("9001", name="Web Team", user_ids=[11, 22])

    assert session.last["url"] == "https://api.clickup.com/api/v3/workspaces/9001/chat/channels"
    assert session.last["json"]["name"] == "Web Team"
    assert session.last["json"]["user_ids"] == [11, 22]
    assert session.last["json"]["visibility"] == "PRIVATE"
    # ClickUp returned no url, so we synthesize one that parses back.
    assert channel["url"] == "https://app.clickup.com/9001/chat/r/chan-77"


def test_create_chat_channel_omits_empty_user_ids():
    """ClickUp rejects a null/empty user_ids array."""
    session = RecordingSession(FakeResponse(200, {"id": "chan-1"}))

    ClickUpClient("pk_test", session=session).create_chat_channel("9001", name="X", user_ids=[])

    assert "user_ids" not in session.last["json"]


def test_create_chat_channel_keeps_a_url_clickup_provided():
    session = RecordingSession(
        FakeResponse(200, {"id": "chan-77", "url": "https://real.clickup.com/9001/chat/r/chan-77"})
    )

    channel = ClickUpClient("pk_test", session=session).create_chat_channel("9001", name="X")

    assert channel["url"] == "https://real.clickup.com/9001/chat/r/chan-77"


def test_post_chat_sends_followers_when_given():
    session = RecordingSession(FakeResponse(200, {"id": "msg-1"}))

    ClickUpClient("pk_test", session=session).post_chat("9001", "chan-77", "hi", followers=[11])

    assert session.last["json"]["followers"] == [11]
    assert session.last["json"]["content"] == "hi"
    assert session.last["json"]["content_format"] == "text/md"


def test_post_chat_omits_followers_when_empty():
    session = RecordingSession(FakeResponse(200, {"id": "msg-1"}))

    ClickUpClient("pk_test", session=session).post_chat("9001", "chan-77", "hi", followers=[])

    assert "followers" not in session.last["json"]
