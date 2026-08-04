import pytest

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import InvitationService, TeamService
from apps.common.exceptions import ConflictError, ForbiddenError, NotFoundError


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

    def test_remove_owner_raises_forbidden(self):
        owner = User.objects.create_user(email="rem@svc.com", password="Pass123!")
        team = TeamService.create(name="Agency C", owner=owner)
        with pytest.raises(ForbiddenError):
            TeamService.remove_member(team=team, user=owner)

    def test_remove_nonmember_raises_not_found(self):
        owner = User.objects.create_user(email="rmnf@svc.com", password="Pass123!")
        stranger = User.objects.create_user(
            email="stranger@svc.com", password="Pass123!"
        )
        team = TeamService.create(name="Agency D", owner=owner)
        with pytest.raises(NotFoundError):
            TeamService.remove_member(team=team, user=stranger)

    def test_update_member_role(self):
        owner = User.objects.create_user(email="upd_o@svc.com", password="Pass123!")
        member = User.objects.create_user(email="upd_m@svc.com", password="Pass123!")
        team = TeamService.create(name="Agency E", owner=owner)
        TeamService.add_member(
            team=team, user=member, role=TeamMembership.Role.VIEWER
        )
        updated = TeamService.update_member_role(
            team=team, user=member, role=TeamMembership.Role.MANAGER
        )
        assert updated.role == TeamMembership.Role.MANAGER


@pytest.mark.django_db
class TestInvitationService:
    def test_create_invitation_generates_token(self):
        owner = User.objects.create_user(email="inv_o@svc.com", password="Pass123!")
        team = TeamService.create(name="Invite Agency", owner=owner)
        invitation = InvitationService.invite(
            team=team,
            invited_by=owner,
            email="newmember@client.com",
            role=TeamMembership.Role.DEVELOPER,
        )
        assert len(invitation.token) > 20

    def test_accept_invitation_creates_membership(self):
        owner = User.objects.create_user(email="acc_o@svc.com", password="Pass123!")
        new_user = User.objects.create_user(
            email="acc_m@svc.com", password="Pass123!"
        )
        team = TeamService.create(name="Accept Agency", owner=owner)
        invitation = InvitationService.invite(
            team=team,
            invited_by=owner,
            email=new_user.email,
            role=TeamMembership.Role.DEVELOPER,
        )
        InvitationService.accept(token=invitation.token, user=new_user)
        assert TeamMembership.objects.filter(user=new_user, team=team).exists()

    def test_accept_wrong_user_raises_forbidden(self):
        owner = User.objects.create_user(email="fw_o@svc.com", password="Pass123!")
        other = User.objects.create_user(email="fw_x@svc.com", password="Pass123!")
        team = TeamService.create(name="FW Agency", owner=owner)
        invitation = InvitationService.invite(
            team=team,
            invited_by=owner,
            email="someone@else.com",
            role=TeamMembership.Role.VIEWER,
        )
        with pytest.raises(ForbiddenError):
            InvitationService.accept(token=invitation.token, user=other)

    def test_invite_existing_member_raises_conflict(self):
        owner = User.objects.create_user(email="em_o@svc.com", password="Pass123!")
        member = User.objects.create_user(email="em_m@svc.com", password="Pass123!")
        team = TeamService.create(name="EM Agency", owner=owner)
        TeamService.add_member(team=team, user=member, role=TeamMembership.Role.VIEWER)
        with pytest.raises(ConflictError):
            InvitationService.invite(
                team=team,
                invited_by=owner,
                email=member.email,
                role=TeamMembership.Role.DEVELOPER,
            )
