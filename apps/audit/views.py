import csv

from django.http import HttpResponse
from rest_framework import generics, permissions
from rest_framework.views import APIView

from apps.audit.models import ActivityLog
from apps.audit.serializers import ActivityLogSerializer
from apps.common.permissions import IsTeamMember

_MANAGER_ROLES = {"manager", "owner"}


def _role(user, team) -> str:
    from apps.accounts.models import TeamMembership
    try:
        return TeamMembership.objects.get(user=user, team=team).role
    except TeamMembership.DoesNotExist:
        return "viewer"


def _scoped_logs(request):
    """Role-aware base queryset: managers/owners see the whole team (optionally
    filtered by ?user_id); everyone else sees only their own activity."""
    user = request.user
    team = user.active_team
    if team is None:
        return ActivityLog.objects.none()

    is_manager = _role(user, team) in _MANAGER_ROLES
    if is_manager:
        user_id = request.query_params.get("user_id")
        qs = ActivityLog.objects.filter(team=team)
        if user_id:
            qs = qs.filter(actor_id=user_id)
    else:
        qs = ActivityLog.objects.filter(team=team, actor=user)
    return qs.select_related("actor")


def _apply_filters(qs, request):
    """Shared query-param filters: action, resource_type, website_id, start/end, q."""
    params = request.query_params
    action = params.get("action")
    resource_type = params.get("resource_type")
    website_id = params.get("website_id")
    start = params.get("start")
    end = params.get("end")
    q = params.get("q")

    if website_id:
        # Website-scoped actions carry the id either as the resource itself or
        # in metadata (script reviews, change acknowledgements).
        from django.db.models import Q

        qs = qs.filter(
            Q(resource_id=website_id) | Q(metadata__website_id=website_id)
        )
    if action:
        qs = qs.filter(action=action)
    if resource_type:
        qs = qs.filter(resource_type=resource_type)
    if start:
        qs = qs.filter(created_at__gte=start)
    if end:
        qs = qs.filter(created_at__lte=end)
    if q:
        qs = qs.filter(description__icontains=q)
    return qs


class ActivityLogListView(generics.ListAPIView):
    """GET /api/v1/logs/ — searchable activity log.

    Filters: ?action= &resource_type= &start= &end= &q= &user_id= (managers).
    """

    serializer_class = ActivityLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        return _apply_filters(_scoped_logs(self.request), self.request)


class ActivityLogExportView(APIView):
    """GET /api/v1/logs/export/ — CSV export of the (filtered) activity log."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    _COLUMNS = [
        "created_at", "actor_email", "action", "resource_type",
        "resource_id", "description", "ip_address",
    ]

    def get(self, request):
        qs = _apply_filters(_scoped_logs(request), request).order_by("-created_at")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="activity-log.csv"'
        writer = csv.writer(response)
        writer.writerow(self._COLUMNS)
        for log in qs.iterator():
            writer.writerow([
                log.created_at.isoformat(),
                log.actor.email if log.actor else "system",
                log.action,
                log.resource_type,
                log.resource_id,
                log.description,
                log.ip_address or "",
            ])
        return response
