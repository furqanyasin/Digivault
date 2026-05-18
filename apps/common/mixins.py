class TeamScopedMixin:
    """View mixin that injects the authenticated user's active team into every
    queryset call, providing defence-in-depth data isolation.

    The model's manager must expose `.for_team(team)` (via TeamScopedQuerySet).
    """

    def get_queryset(self):
        qs = super().get_queryset()
        team = self.request.user.active_team
        if team is None:
            return qs.none()
        return qs.for_team(team)
