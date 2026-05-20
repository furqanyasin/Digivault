from rest_framework import generics, permissions
from rest_framework.response import Response

from apps.audit.models import ActivityLog
from apps.audit.serializers import ActivityLogSerializer
from apps.common.permissions import IsTeamMember


class ActivityLogListView(generics.ListAPIView):
    """GET /api/v1/logs/

    All members see their own logs.
    Managers and owners can filter by user_id to see any member's logs,
    or omit user_id to see all team logs.
    """

    serializer_class = ActivityLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    _MANAGER_ROLES = {"manager", "owner"}

    def get_queryset(self):
        user = self.request.user
        team = user.active_team
        if team is None:
            return ActivityLog.objects.none()

        role = self._get_role(user, team)
        is_manager = role in self._MANAGER_ROLES

        # Managers/owners: optionally filter by team member
        user_id = self.request.query_params.get("user_id")
        if is_manager and user_id:
            return ActivityLog.objects.filter(team=team, actor_id=user_id).select_related("actor")
        if is_manager:
            return ActivityLog.objects.filter(team=team).select_related("actor")

        # Everyone else: own logs only
        return ActivityLog.objects.filter(team=team, actor=user).select_related("actor")

    @staticmethod
    def _get_role(user, team) -> str:
        from apps.accounts.models import TeamMembership
        try:
            m = TeamMembership.objects.get(user=user, team=team)
            return m.role
        except TeamMembership.DoesNotExist:
            return "viewer"
