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
    def create(name: str, owner: User, plan: str | None = None, require_2fa: bool | None = None) -> Team:
        """Create a team and set it as the owner's active team.

        Without an explicit plan, a team made by someone whose current team is
        on the internal plan (a new department) stays internal and keeps 2FA
        mandatory. Anyone else gets the free plan.
        """
        current = owner.active_team
        if plan is None:
            plan = Team.Plan.INTERNAL if current and current.plan == Team.Plan.INTERNAL else Team.Plan.FREE
        if require_2fa is None:
            require_2fa = plan == Team.Plan.INTERNAL
        team = Team.objects.create(name=name, owner=owner, plan=plan, require_2fa=require_2fa)
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
