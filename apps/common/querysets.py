from django.db import models


class TeamScopedQuerySet(models.QuerySet):
    """Mixin queryset that restricts results to a single team.

    Usage — on any model with a `team` FK:

        class Website(BaseModel):
            team = models.ForeignKey(Team, ...)
            objects = TeamScopedManager.from_queryset(TeamScopedQuerySet)()

        # In a view:
        Website.objects.for_team(request.user.active_team)
    """

    def for_team(self, team) -> "TeamScopedQuerySet":
        return self.filter(team=team)

    def for_user(self, user) -> "TeamScopedQuerySet":
        """Restrict to teams the user is a member of."""
        return self.filter(team__memberships__user=user)


class ActiveQuerySet(models.QuerySet):
    """Queryset that adds an `active()` filter for models with `is_active`."""

    def active(self) -> "ActiveQuerySet":
        return self.filter(is_active=True)

    def inactive(self) -> "ActiveQuerySet":
        return self.filter(is_active=False)
