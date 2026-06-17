from rest_framework.permissions import BasePermission


class IsTeamMember(BasePermission):
    """Grants access to any authenticated user who is a member of the team
    identified by the `team_pk` URL kwarg or the user's active team."""

    message = "You are not a member of this team."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Lazy import to avoid circular dependency at module load time
        from apps.accounts.models import TeamMembership

        team_pk = view.kwargs.get("team_pk")
        if team_pk:
            return TeamMembership.objects.filter(
                user=request.user, team_id=team_pk
            ).exists()
        return request.user.active_team is not None


class RolePermission(BasePermission):
    """Enforce minimum team role.

    Set `required_role` on the view class to the minimum role string.
    Role hierarchy (ascending privilege): viewer < developer < manager < owner
    """

    ROLE_LEVELS = {
        "viewer": 1,
        # Member-level roles share the developer tier.
        "developer": 2,
        "custom": 2,
        "editor": 2,
        "seo": 2,
        "manager": 3,
        "owner": 4,
    }

    required_role: str = "viewer"

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        from apps.accounts.models import TeamMembership

        required = self.ROLE_LEVELS.get(getattr(view, "required_role", "viewer"), 1)
        team = request.user.active_team
        if team is None:
            return False

        try:
            membership = TeamMembership.objects.get(user=request.user, team=team)
        except TeamMembership.DoesNotExist:
            return False

        actual = self.ROLE_LEVELS.get(membership.role, 0)
        return actual >= required
