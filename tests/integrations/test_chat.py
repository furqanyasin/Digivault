"""notify_problem() — announce a website problem in the team's ClickUp channel.

Two invariants matter most. First, the owning developer is notified through the
message's `followers` field, not through inline mention text, because ClickUp
documents no request-side @-mention syntax for v3 chat. Second, nothing here may
raise into an alert path: a ClickUp outage must not take down the email that
already went out.
"""
import pytest

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.clients.models import Client
from apps.integrations.chat import (
    mention_for,
    notify_problem,
    notify_recovery,
    resolve_owner,
)
from apps.integrations.clickup import ClickUpClient
from apps.integrations.members import set_member_link
from apps.integrations.models import ClickUpTaskLink
from apps.websites.models import Website

CHAT_URL = "https://app.clickup.com/9001/chat/r/chan-77"


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class RecordingSession:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on or ""

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json})
        if self.fail_on and self.fail_on in url:
            return FakeResponse(500, {})
        if url.endswith("/task"):
            return FakeResponse(200, {"id": "task-1", "url": "https://app.clickup.com/t/86a1"})
        return FakeResponse(200, {"id": "x"})

    def urls(self):
        return [c["url"] for c in self.calls]

    def chat_body(self):
        for c in self.calls:
            if "/messages" in c["url"]:
                return c["json"]
        return None


@pytest.fixture
def setup(db):
    owner = User.objects.create_user(email="chatowner@x.io", password="Pass123!")
    team = TeamService.create(name="Chat Co", owner=owner)
    team.clickup_api_token = "pk_test"
    team.clickup_list_id = "list-42"
    team.clickup_chat_url = CHAT_URL
    team.save()

    dev = User.objects.create_user(email="jane@x.io", password="Pass123!")
    TeamMembership.objects.create(user=dev, team=team, role=TeamMembership.Role.DEVELOPER)
    set_member_link(team, dev, "11", "jane")

    client_rec = Client.objects.create(team=team, name="Example Co", assigned_to=dev)
    website = Website.objects.create(
        team=team, client=client_rec, name="Example Co", domain="example.com"
    )
    return team, dev, website


def _api(session):
    return ClickUpClient("pk_test", session=session)


# -- resolve_owner ---------------------------------------------------------

def test_resolve_owner_returns_the_clients_assignee(setup):
    _, dev, website = setup
    assert resolve_owner(website) == dev


def test_resolve_owner_is_none_when_the_website_has_no_client(setup):
    team, _, _ = setup
    orphan = Website.objects.create(team=team, name="Orphan", domain="orphan.io")
    assert resolve_owner(orphan) is None


def test_resolve_owner_is_none_when_the_client_is_unassigned(setup):
    _, _, website = setup
    website.client.assigned_to = None
    website.client.save()
    website.refresh_from_db()
    assert resolve_owner(website) is None


# -- mention_for ----------------------------------------------------------

def test_mention_for_a_mapped_user_is_an_at_mention(setup):
    team, dev, _ = setup
    text, cu_id = mention_for(team, dev)
    assert text == "@jane"
    assert cu_id == "11"


def test_mention_for_an_unmapped_user_is_a_bare_name(setup):
    """No broken-looking @ for someone ClickUp does not know."""
    team, _, _ = setup
    stranger = User.objects.create_user(email="nomap@x.io", password="Pass123!")
    TeamMembership.objects.create(user=stranger, team=team, role=TeamMembership.Role.DEVELOPER)

    text, cu_id = mention_for(team, stranger)

    assert not text.startswith("@")
    assert "nomap@x.io" in text
    assert cu_id is None


def test_mention_for_none_is_unassigned(setup):
    team, _, _ = setup
    assert mention_for(team, None) == ("unassigned", None)


# -- notify_problem -------------------------------------------------------

def test_notify_problem_posts_to_the_parsed_workspace_and_channel(setup):
    _, _, website = setup
    session = RecordingSession()

    sent = notify_problem(
        website, subject="monitor:1:down", title="site is DOWN",
        detail="HTTP 503", client=_api(session),
    )

    assert sent is True
    assert (
        "https://api.clickup.com/api/v3/workspaces/9001/chat/channels/chan-77/messages"
        in session.urls()
    )


def test_the_owner_is_notified_via_followers(setup):
    _, _, website = setup
    session = RecordingSession()

    notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    assert session.chat_body()["followers"] == ["11"]


def test_the_message_names_the_site_the_owner_and_the_task(setup):
    _, _, website = setup
    session = RecordingSession()

    notify_problem(
        website, subject="monitor:1:down", title="site is DOWN",
        detail="HTTP 503 from https://example.com/", client=_api(session),
    )

    content = session.chat_body()["content"]
    assert "**Example Co**" in content
    assert "site is DOWN" in content
    assert "example.com" in content
    assert "@jane" in content
    assert "HTTP 503 from https://example.com/" in content
    assert "https://app.clickup.com/t/86a1" in content


def test_a_task_is_opened_for_the_problem(setup):
    team, _, website = setup
    session = RecordingSession()

    notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    assert ClickUpTaskLink.objects.filter(team=team, subject="monitor:1:down").count() == 1


def test_the_task_link_line_is_omitted_when_no_list_is_configured(setup):
    team, _, website = setup
    team.clickup_list_id = ""
    team.save()
    website.refresh_from_db()
    session = RecordingSession()

    notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    content = session.chat_body()["content"]
    assert "→" not in content
    assert ClickUpTaskLink.objects.count() == 0


def test_an_unset_chat_url_sends_nothing(setup):
    team, _, website = setup
    team.clickup_chat_url = ""
    team.save()
    website.refresh_from_db()
    session = RecordingSession()

    sent = notify_problem(
        website, subject="monitor:1:down", title="down", detail="x", client=_api(session)
    )

    assert sent is False
    assert session.calls == []


def test_a_clickup_failure_is_swallowed(setup):
    """A ClickUp outage must not propagate into the alert path that called us."""
    _, _, website = setup
    session = RecordingSession(fail_on="/messages")

    sent = notify_problem(
        website, subject="monitor:1:down", title="down", detail="x", client=_api(session)
    )

    assert sent is False


def test_an_unassigned_site_still_posts(setup):
    _, _, website = setup
    website.client.assigned_to = None
    website.client.save()
    website.refresh_from_db()
    session = RecordingSession()

    sent = notify_problem(
        website, subject="monitor:1:down", title="down", detail="x", client=_api(session)
    )

    assert sent is True
    assert "unassigned" in session.chat_body()["content"]
    assert "followers" not in session.chat_body()


# -- notify_recovery ------------------------------------------------------

def test_recovery_closes_the_open_task_link(setup):
    team, _, website = setup
    session = RecordingSession()
    notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    notify_recovery(website, subject="monitor:1:down", title="back UP", client=_api(session))

    link = ClickUpTaskLink.objects.get(team=team, subject="monitor:1:down")
    assert link.closed_at is not None


def test_recovery_posts_a_recovery_line(setup):
    _, _, website = setup
    session = RecordingSession()

    notify_recovery(website, subject="monitor:1:down", title="back UP", client=_api(session))

    assert "back UP" in session.chat_body()["content"]
    assert "✅" in session.chat_body()["content"]
