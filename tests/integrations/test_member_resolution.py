"""Resolving a ClickUp member link on demand, at alert time.

`sync_member_links` only runs when a manager opens Settings, and it joins on
email alone. Anyone hired since the last sync — or anyone whose ClickUp address
differs from their Stacks Monitor one — therefore had no link, which is why alerts
rendered "Managed by: Junaid" as a bare name and left him out of `followers`
entirely. `resolve_member_link` closes that gap: it looks the person up the
first time an alert needs them, falls back to name matching, and stores the
result so the next alert is free.
"""
import pytest
from django.core.cache import cache

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.integrations.clickup import ClickUpClient
from apps.integrations.members import resolve_member_link, set_member_link
from apps.integrations.models import ClickUpMemberLink


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class WorkspaceSession:
    def __init__(self, members, status_code=200):
        self.calls = []
        self._members = members
        self._status = status_code

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append(url)
        if self._status != 200:
            return FakeResponse(self._status, {})
        return FakeResponse(200, {"teams": [{"id": "9001", "members": self._members}]})


def _member(user_id, email, username="cu"):
    return {"user": {"id": user_id, "email": email, "username": username}}


def _client(session):
    return ClickUpClient("pk_test", session=session)


@pytest.fixture
def team_with_dev(db):
    cache.clear()
    owner = User.objects.create_user(email="resolveowner@x.io", password="Pass123!")
    team = TeamService.create(name="Resolve Co", owner=owner)
    team.clickup_api_token = "pk_test"
    team.save()
    dev = User.objects.create_user(
        email="junaid@example.com", password="Pass123!",
        first_name="Junaid", last_name="Naseem",
    )
    TeamMembership.objects.create(user=dev, team=team, role=TeamMembership.Role.DEVELOPER)
    yield team, dev
    cache.clear()


def test_an_existing_link_is_returned_without_calling_clickup(team_with_dev):
    team, dev = team_with_dev
    set_member_link(team, dev, "11", "junaid")
    session = WorkspaceSession([])

    link = resolve_member_link(team, dev, client=_client(session))

    assert link.clickup_user_id == "11"
    assert session.calls == []


def test_an_unlinked_member_is_looked_up_by_email_and_stored(team_with_dev):
    """The gap that made alerts say "Junaid" instead of "@junaid"."""
    team, dev = team_with_dev
    session = WorkspaceSession([_member(42, "JUNAID@example.com", "junaid")])

    link = resolve_member_link(team, dev, client=_client(session))

    assert link.clickup_user_id == "42"
    assert link.clickup_username == "junaid"
    assert ClickUpMemberLink.objects.get(team=team, user=dev).clickup_user_id == "42"


def test_a_member_whose_clickup_email_differs_is_matched_on_name(team_with_dev):
    """Agency staff routinely sign into ClickUp with a personal address."""
    team, dev = team_with_dev
    session = WorkspaceSession([_member(43, "junaid.personal@gmail.com", "Junaid Naseem")])

    link = resolve_member_link(team, dev, client=_client(session))

    assert link.clickup_user_id == "43"


def test_two_people_sharing_a_handle_resolve_to_neither(team_with_dev):
    """Pinging the wrong person about an outage is worse than pinging nobody."""
    team, dev = team_with_dev
    session = WorkspaceSession([
        _member(51, "one@elsewhere.io", "Junaid Naseem"),
        _member(52, "two@elsewhere.io", "junaid.naseem"),
    ])

    assert resolve_member_link(team, dev, client=_client(session)) is None


def test_a_shared_mailbox_is_not_matched_on_its_local_part(team_with_dev):
    """info@agency.com and info@client.com are not the same person."""
    team, _ = team_with_dev
    shared = User.objects.create_user(email="info@agency.io", password="Pass123!")
    TeamMembership.objects.create(user=shared, team=team, role=TeamMembership.Role.DEVELOPER)
    session = WorkspaceSession([_member(53, "info@someclient.io", "clientdesk")])

    assert resolve_member_link(team, shared, client=_client(session)) is None


def test_a_member_clickup_does_not_know_resolves_to_nothing(team_with_dev):
    team, dev = team_with_dev
    session = WorkspaceSession([_member(44, "someone@else.io", "someone")])

    assert resolve_member_link(team, dev, client=_client(session)) is None
    assert ClickUpMemberLink.objects.filter(team=team, user=dev).count() == 0


def test_the_workspace_roster_is_fetched_once_for_a_burst_of_alerts(team_with_dev):
    """An outage fires repeatedly; one ClickUp round-trip per team, not per alert."""
    team, dev = team_with_dev
    stranger = User.objects.create_user(email="nobody@x.io", password="Pass123!")
    TeamMembership.objects.create(user=stranger, team=team, role=TeamMembership.Role.DEVELOPER)
    session = WorkspaceSession([_member(44, "someone@else.io", "someone")])

    resolve_member_link(team, dev, client=_client(session))
    resolve_member_link(team, stranger, client=_client(session))

    assert len(session.calls) == 1


def test_a_clickup_outage_resolves_to_nothing_rather_than_raising(team_with_dev):
    """Nothing in the alert path may raise — email has already gone out."""
    team, dev = team_with_dev
    session = WorkspaceSession([], status_code=500)

    assert resolve_member_link(team, dev, client=_client(session)) is None


def test_a_team_without_a_token_resolves_to_nothing(db):
    cache.clear()
    owner = User.objects.create_user(email="notoken@x.io", password="Pass123!")
    team = TeamService.create(name="No Token Co", owner=owner)

    assert resolve_member_link(team, owner) is None
