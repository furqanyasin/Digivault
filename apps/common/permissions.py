from rest_framework.permissions import SAFE_METHODS, BasePermission


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


#: Ascending privilege. Member-level roles share the `developer` tier: an SEO
#: executive and a developer are both "staff who do the work", and every rule
#: here that wants to distinguish them wants `manager` instead.
ROLE_LEVELS = {
    "viewer": 1,
    "developer": 2,
    "custom": 2,
    "editor": 2,
    "seo": 2,
    "seo_executive": 2,
    "manager": 3,
    "owner": 4,
}

#: Day-to-day work: create and edit monitors, alert rules, status page
#: incidents, trigger a scan, acknowledge a change.
ROLE_MEMBER = "developer"
#: Structural or destructive: delete a website, rotate a site_id, manage the
#: client book, touch the vault.
ROLE_MANAGER = "manager"


def role_level(user, team) -> int:
    """This user's privilege level in `team`. 0 when they are not a member."""
    from apps.accounts.models import TeamMembership

    if team is None or not user or not user.is_authenticated:
        return 0
    membership = TeamMembership.objects.filter(user=user, team=team).first()
    if membership is None:
        return 0
    return ROLE_LEVELS.get(membership.role, 0)


class RolePermission(BasePermission):
    """Enforce a minimum team role on *every* method of a view.

    Set `required_role` on the view class. Use this where reading is itself
    privileged — the credential vault's group grants, for instance. Where
    reading is fine and only writing is not, use `TeamRolePermission`, which
    would otherwise lock viewers out of pages they are meant to see.
    """

    ROLE_LEVELS = ROLE_LEVELS

    required_role: str = "viewer"

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        team = request.user.active_team
        if team is None:
            return False

        required = ROLE_LEVELS.get(getattr(view, "required_role", "viewer"), 1)
        return role_level(request.user, team) >= required


class TeamRolePermission(BasePermission):
    """Read for any member; write for staff; delete for managers.

    `RolePermission` existed with a four-tier hierarchy and was wired to four
    views out of roughly a hundred, so the role column was decorative almost
    everywhere: a `viewer` could create and delete websites and monitors, rename
    the team, write alert rules, import and export the whole client book, and
    trigger scans. The reason it stayed unused is that it gates every method at
    one level, and almost every view here both reads and writes — applying it
    would have taken the viewer's read access away along with the writes.

    Splitting by method is what makes it applicable, so it is one class rather
    than a per-view judgement call:

    - safe methods (GET/HEAD/OPTIONS) → team membership, nothing more
    - unsafe methods → `view.write_role` (default `developer`)
    - DELETE → `view.destroy_role` (default `manager`)

    A view needing something finer sets `action_roles`, keyed by DRF action
    name, ``action:METHOD`` for an action that serves both, or a bare HTTP
    method::

        action_roles = {
            "regenerate_snippet": ROLE_MANAGER,   # POST-only action
            "assignments:PUT": ROLE_MANAGER,      # but its GET stays open
        }
    """

    message = "Your role does not allow this action."

    #: Defaults, overridable per view.
    write_role: str = ROLE_MEMBER
    destroy_role: str = ROLE_MANAGER

    def _required_role(self, request, view) -> str | None:
        """The role this request needs, or None when membership is enough."""
        overrides = getattr(view, "action_roles", None) or {}

        action = getattr(view, "action", None)
        if action:
            # Most specific first: an action that serves both GET and PUT needs
            # to gate the PUT without taking the GET away.
            if f"{action}:{request.method}" in overrides:
                return overrides[f"{action}:{request.method}"]
            if action in overrides:
                return overrides[action]
        if request.method in overrides:
            return overrides[request.method]

        if request.method in SAFE_METHODS:
            return None
        if request.method == "DELETE":
            return getattr(view, "destroy_role", self.destroy_role)
        return getattr(view, "write_role", self.write_role)

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        team = request.user.active_team
        if team is None:
            return False

        required = self._required_role(request, view)
        if required is None:
            # Reads cost no extra query: having an active team is exactly what
            # IsTeamMember already established, and the queryset is team-scoped
            # regardless. Looking the membership up here would add a round trip
            # to every list endpoint to learn something no read depends on.
            return True

        return role_level(request.user, team) >= ROLE_LEVELS.get(required, 1)
