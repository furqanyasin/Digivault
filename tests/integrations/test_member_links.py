"""Matching Stacks Monitor users to ClickUp members.

Email is the only join key ClickUp gives us, and it is frequently different
from the Stacks Monitor one — so "unmatched" is a first-class result the UI shows,
not an error.
"""
import pytest

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.integrations.clickup import ClickUpClient
from apps.integrations.members import set_member_link, sync_member_links
from apps.integrations.models import ClickUpMemberLink


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class WorkspaceSession:
    """Returns one workspace whose members are `members`."""

    def __init__(self, members):
        self.calls = []
        self._members = members

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json})
        return FakeResponse(200, {"teams": [{"id": "9001", "name": "WS", "members": self._members}]})


def _member(user_id, email, username="cu"):
    return {"user": {"id": user_id, "email": email, "username": username}}


def _client(session):
    return ClickUpClient("pk_test", session=session)


@pytest.fixture
def team_with_dev(db):
    owner = User.objects.create_user(email="owner@x.io", password="Pass123!")
    t = TeamService.create(name="Links Co", owner=owner)
    t.clickup_api_token = "pk_test"
    t.save()
    dev = User.objects.create_user(email="Jane@X.io", password="Pass123!")
    TeamMembership.objects.create(user=dev, team=t, role=TeamMembership.Role.DEVELOPER)
    return t, dev


def test_matching_is_case_insensitive_on_email(team_with_dev):
    team, dev = team_with_dev
    session = WorkspaceSession([_member(11, "jane@x.io", "jane")])

    result = sync_member_links(team, client=_client(session))

    link = ClickUpMemberLink.objects.get(team=team, user=dev)
    assert link.clickup_user_id == "11"
    assert link.clickup_username == "jane"
    assert result["workspace_id"] == "9001"
    assert str(dev.id) in {m["user_id"] for m in result["matched"]}


def test_a_member_clickup_does_not_know_is_reported_unmatched(team_with_dev):
    team, dev = team_with_dev
    session = WorkspaceSession([_member(11, "someone-else@x.io")])

    result = sync_member_links(team, client=_client(session))

    assert ClickUpMemberLink.objects.filter(team=team, user=dev).count() == 0
    assert str(dev.id) in {m["user_id"] for m in result["unmatched"]}


def test_syncing_twice_updates_rather_than_duplicates(team_with_dev):
    team, dev = team_with_dev

    sync_member_links(team, client=_client(WorkspaceSession([_member(11, "jane@x.io", "jane")])))
    sync_member_links(team, client=_client(WorkspaceSession([_member(99, "jane@x.io", "jane2")])))

    link = ClickUpMemberLink.objects.get(team=team, user=dev)
    assert link.clickup_user_id == "99"
    assert link.clickup_username == "jane2"


def test_an_unconfigured_team_syncs_nothing(db):
    owner = User.objects.create_user(email="noconf@x.io", password="Pass123!")
    team = TeamService.create(name="No Token", owner=owner)

    result = sync_member_links(team)

    assert result == {"matched": [], "unmatched": [], "workspace_id": None}


def test_set_member_link_overrides_a_failed_email_match(team_with_dev):
    team, dev = team_with_dev

    link = set_member_link(team, dev, "424242")

    assert link.clickup_user_id == "424242"
    assert ClickUpMemberLink.objects.get(team=team, user=dev).clickup_user_id == "424242"
