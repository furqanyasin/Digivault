"""notify_problem() — announce a website problem in the team's ClickUp channel.

Three invariants matter most. First, one channel carries every client, so a
message has to name the client, the site and the failure on its own. Second,
managers are notified through the message's `followers` field, not through
inline mention text, because ClickUp documents no request-side @-mention syntax
for v3 chat. Third, nothing here may raise into an alert path: a ClickUp outage
must not take down the email that already went out.
"""
import pytest

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.clients.models import Client
from apps.integrations.chat import (
    mention_for,
    mentions_for,
    notify_problem,
    notify_recovery,
    resolve_managers,
    resolve_owner,
)
from apps.integrations.clickup import ClickUpClient
from apps.integrations.members import set_member_link
from apps.integrations.models import ClickUpTaskLink
from apps.websites.models import Website, WebsiteAssignment

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


# -- resolve_managers / mentions_for --------------------------------------

def test_managers_are_the_client_owner_plus_the_sites_assignees(setup):
    """Whoever is on the site today is reachable, not only the account owner."""
    team, dev, website = setup
    helper = User.objects.create_user(email="helper@x.io", password="Pass123!")
    TeamMembership.objects.create(user=helper, team=team, role=TeamMembership.Role.DEVELOPER)
    WebsiteAssignment.objects.create(website=website, user=helper)

    assert resolve_managers(website) == [dev, helper]


def test_a_manager_assigned_twice_is_named_once(setup):
    _, dev, website = setup
    WebsiteAssignment.objects.create(website=website, user=dev)

    assert resolve_managers(website) == [dev]


def test_mentions_name_everyone_and_ping_the_mapped_ones(setup):
    team, dev, website = setup
    stranger = User.objects.create_user(email="nolink@x.io", password="Pass123!")
    TeamMembership.objects.create(user=stranger, team=team, role=TeamMembership.Role.DEVELOPER)
    WebsiteAssignment.objects.create(website=website, user=stranger)

    text, ids = mentions_for(team, resolve_managers(website))

    assert "@jane" in text
    assert "nolink@x.io" in text
    assert ids == ["11"]


def test_mentions_for_nobody_is_unassigned(setup):
    team, _, _ = setup
    assert mentions_for(team, []) == ("unassigned", [])


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


def test_every_manager_is_notified_via_followers(setup):
    team, _, website = setup
    helper = User.objects.create_user(email="helper2@x.io", password="Pass123!")
    TeamMembership.objects.create(user=helper, team=team, role=TeamMembership.Role.DEVELOPER)
    set_member_link(team, helper, "22", "helper")
    WebsiteAssignment.objects.create(website=website, user=helper)

    session = RecordingSession()
    notify_problem(website, subject="monitor:1:down", title="down", client=_api(session))

    assert session.chat_body()["followers"] == ["11", "22"]


def test_the_message_names_the_client_the_site_and_the_managers(setup):
    """One channel holds every client, so the message must identify itself."""
    _, _, website = setup
    website.client.name = "Acme Ltd"
    website.client.save()
    website.refresh_from_db()
    session = RecordingSession()

    notify_problem(
        website, subject="monitor:1:down", title="is DOWN",
        fields=[("Error", "HTTP 503: Service Unavailable"), ("HTTP status", 503)],
        client=_api(session),
    )

    content = session.chat_body()["content"]
    assert "🔴 **Acme Ltd** — Example Co is DOWN" in content
    assert "Client: Acme Ltd" in content
    assert "Website: Example Co (example.com)" in content
    assert "Error: HTTP 503: Service Unavailable" in content
    assert "HTTP status: 503" in content
    assert "Managed by: @jane" in content


def test_a_site_with_no_client_leads_with_the_site(setup):
    team, _, _ = setup
    orphan = Website.objects.create(team=team, name="Orphan", domain="orphan.io")
    session = RecordingSession()

    notify_problem(orphan, subject="monitor:2:down", title="is DOWN", client=_api(session))

    content = session.chat_body()["content"]
    assert content.startswith("🔴 **Orphan** is DOWN")
    assert "Client:" not in content


def test_empty_fields_are_dropped(setup):
    """A blank error must not render as a dangling 'Error:' line."""
    _, _, website = setup
    session = RecordingSession()

    notify_problem(
        website, subject="monitor:1:down", title="is DOWN",
        fields=[("Error", ""), ("HTTP status", None), ("Response time", "120 ms")],
        client=_api(session),
    )

    content = session.chat_body()["content"]
    assert "Error:" not in content
    assert "HTTP status:" not in content
    assert "Response time: 120 ms" in content


def test_no_clickup_task_is_created(setup):
    """Alerts post a message and nothing else — no task, no task list traffic."""
    team, _, website = setup
    session = RecordingSession()

    notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    assert ClickUpTaskLink.objects.filter(team=team).count() == 0
    assert not any(url.endswith("/task") for url in session.urls())


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

def test_recovery_is_rendered_like_the_problem_it_clears(setup):
    """An unmatchable recovery is worse than none — same client, site and shape."""
    _, _, website = setup
    session = RecordingSession()

    notify_recovery(
        website, subject="monitor:1:down", title="is back UP",
        fields=[("Response time", "3490 ms")], client=_api(session),
    )

    content = session.chat_body()["content"]
    assert "✅ **Example Co** — Example Co is back UP" in content
    assert "Website: Example Co (example.com)" in content
    assert "Response time: 3490 ms" in content
    assert "Managed by: @jane" in content
