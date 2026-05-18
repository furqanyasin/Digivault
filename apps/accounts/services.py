from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Team, TeamInvitation, TeamMembership, User
from apps.common.exceptions import ConflictError, ForbiddenError, NotFoundError


class TeamService:
    """All business logic for team lifecycle management.

    Views should call these methods rather than touching models directly.
    This keeps validation and side-effects in one place.
    """

    @staticmethod
    @transaction.atomic
    def create(name: str, owner: User) -> Team:
        """Create a team and set it as the owner's active team."""
        team = Team.objects.create(name=name, owner=owner)
        owner.active_team = team
        owner.save(update_fields=["active_team"])
        return team

    @staticmethod
    @transaction.atomic
    def add_member(
        team: Team, user: User, role: str = TeamMembership.Role.DEVELOPER
    ) -> TeamMembership:
        if TeamMembership.objects.filter(team=team, user=user).exists():
            raise ConflictError(
                f"{user.email} is already a member of {team.name}."
            )
        return TeamMembership.objects.create(team=team, user=user, role=role)

    @staticmethod
    @transaction.atomic
    def remove_member(team: Team, user: User) -> None:
        if user == team.owner:
            raise ForbiddenError("The team owner cannot be removed from the team.")
        deleted, _ = TeamMembership.objects.filter(team=team, user=user).delete()
        if not deleted:
            raise NotFoundError(f"{user.email} is not a member of {team.name}.")

    @staticmethod
    @transaction.atomic
    def update_member_role(team: Team, user: User, role: str) -> TeamMembership:
        if user == team.owner:
            raise ForbiddenError("Cannot change the owner's role.")
        try:
            membership = TeamMembership.objects.get(team=team, user=user)
        except TeamMembership.DoesNotExist:
            raise NotFoundError(f"{user.email} is not a member of {team.name}.")
        membership.role = role
        membership.save(update_fields=["role", "updated_at"])
        return membership


class InvitationService:
    """Business logic for team invitations."""

    @staticmethod
    @transaction.atomic
    def invite(
        team: Team,
        invited_by: User,
        email: str,
        role: str = TeamMembership.Role.DEVELOPER,
    ) -> TeamInvitation:
        if TeamMembership.objects.filter(team=team, user__email=email).exists():
            raise ConflictError(f"{email} is already a member of {team.name}.")
        invitation, created = TeamInvitation.objects.get_or_create(
            team=team,
            email=email,
            defaults={"invited_by": invited_by, "role": role},
        )
        if not created and invitation.accepted:
            raise ConflictError(f"{email} has already accepted an invitation.")
        return invitation

    @staticmethod
    @transaction.atomic
    def accept(token: str, user: User) -> TeamMembership:
        try:
            invitation = TeamInvitation.objects.select_for_update().get(
                token=token, accepted=False
            )
        except TeamInvitation.DoesNotExist:
            raise NotFoundError("Invitation not found or already accepted.")

        if invitation.email != user.email:
            raise ForbiddenError(
                "This invitation was sent to a different email address."
            )

        membership = TeamService.add_member(
            team=invitation.team, user=user, role=invitation.role
        )
        invitation.accepted = True
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted", "accepted_at"])

        if user.active_team is None:
            user.active_team = invitation.team
            user.save(update_fields=["active_team"])

        return membership
