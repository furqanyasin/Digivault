from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.alerts.models import AlertRule, Notification
from apps.alerts.serializers import AlertRuleSerializer, NotificationSerializer
from apps.common.permissions import IsTeamMember, RolePermission


class AlertRuleListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/alert-rules/"""

    serializer_class = AlertRuleSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return AlertRule.objects.none()
        return AlertRule.objects.filter(team=team)

    def perform_create(self, serializer):
        serializer.save(team=self.request.user.active_team)


class AlertRuleDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/alert-rules/<pk>/"""

    serializer_class = AlertRuleSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return AlertRule.objects.none()
        return AlertRule.objects.filter(team=team)


class NotificationListView(generics.ListAPIView):
    """GET /api/v1/notifications/ — team-wide notification feed."""

    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return Notification.objects.none()
        qs = Notification.objects.filter(team=team).select_related(
            "website", "script_change"
        )
        unread = self.request.query_params.get("unread")
        if unread == "true":
            qs = qs.filter(read=False)
        return qs


class MarkNotificationsReadView(APIView):
    """POST /api/v1/notifications/mark-read/ — bulk mark as read."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request):
        team = request.user.active_team
        ids = request.data.get("ids", [])
        now = timezone.now()

        if ids:
            Notification.objects.filter(
                pk__in=ids, team=team, read=False
            ).update(read=True, read_at=now)
        else:
            # Mark all unread for this team
            Notification.objects.filter(team=team, read=False).update(
                read=True, read_at=now
            )

        return Response({"detail": "Marked as read."})
