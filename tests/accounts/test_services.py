import pytest

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.common.exceptions import ConflictError


@pytest.mark.django_db
class TestTeamService:
    def test_create_team_sets_active_team_on_owner(self):
        owner = User.objects.create_user(email="owner@svc.com", password="Pass123!")
        team = TeamService.create(name="My Agency", owner=owner)
        owner.refresh_from_db()
        assert owner.active_team == team

    def test_add_member_creates_membership(self):
        owner = User.objects.create_user(email="o@svc.com", password="Pass123!")
        member = User.objects.create_user(email="m@svc.com", password="Pass123!")
        team = TeamService.create(name="Agency A", owner=owner)
        membership = TeamService.add_member(
            team=team, user=member, role=TeamMembership.Role.DEVELOPER
        )
        assert membership.role == TeamMembership.Role.DEVELOPER

    def test_add_member_duplicate_raises_conflict(self):
        owner = User.objects.create_user(email="dup@svc.com", password="Pass123!")
        member = User.objects.create_user(email="dup2@svc.com", password="Pass123!")
        team = TeamService.create(name="Agency B", owner=owner)
        TeamService.add_member(team=team, user=member, role=TeamMembership.Role.VIEWER)
        with pytest.raises(ConflictError):
            TeamService.add_member(
                team=team, user=member, role=TeamMembership.Role.VIEWER
            )
