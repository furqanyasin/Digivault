from django.db import transaction

from apps.accounts.models import Team, TeamMembership, User
from apps.common.exceptions import ConflictError


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
