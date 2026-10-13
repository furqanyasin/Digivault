"""A WebSocket subscription is not authorised forever by one check at connect.

The consumer validated a JWT once and then held the team's alert group for as
long as the tab stayed open. The access token it presented expires in fifteen
minutes; the subscription did not expire at all. So somebody removed from a team
kept receiving that team's alerts — script changes, site names, severities — for
as long as they left the dashboard open, which is a page people leave open.

Two holes, and they are separate: connect did not check membership at all (it
trusted `user.active_team`, which removing a member does not clear), and nothing
re-checked afterwards.
"""

import pytest

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.alerts.consumers import AlertConsumer

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="ws_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="WS Agency", owner=owner)


@pytest.fixture
def member(team):
    user = User.objects.create_user(email="ws_member@test.com", password="Pass123!")
    TeamMembership.objects.create(
        user=user, team=team, role=TeamMembership.Role.DEVELOPER
    )
    user.active_team = team
    user.save(update_fields=["active_team"])
    return user


def _token_for(user) -> str:
    from rest_framework_simplejwt.tokens import AccessToken

    return str(AccessToken.for_user(user))


def test_a_member_validates(member, team):
    user, resolved_team = AlertConsumer._validate_token(_token_for(member))
    assert user is not None
    assert resolved_team.pk == team.pk


def test_a_removed_member_does_not_validate_even_with_a_valid_token(member, team):
    """`active_team` survives the removal — membership is what must be checked."""
    token = _token_for(member)
    TeamMembership.objects.filter(user=member, team=team).delete()

    member.refresh_from_db()
    assert member.active_team_id == team.pk, "the stale pointer is the whole point"

    user, resolved_team = AlertConsumer._validate_token(token)
    assert user is None
    assert resolved_team is None


def test_a_garbage_token_does_not_validate():
    assert AlertConsumer._validate_token("not-a-jwt") == (None, None)


class TestOpenConnectionRecheck:
    """The periodic re-check is what closes an *already open* connection."""

    def _consumer(self, user, team):
        consumer = AlertConsumer()
        consumer.user = user
        consumer.team = team
        return consumer

    def test_reports_still_a_member(self, member, team):
        assert self._consumer(member, team)._is_still_member() is True

    def test_reports_no_longer_a_member(self, member, team):
        TeamMembership.objects.filter(user=member, team=team).delete()
        assert self._consumer(member, team)._is_still_member() is False
