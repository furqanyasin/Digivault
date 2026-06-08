from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.alerts.models import AlertRule, AlertSuppression, Notification
from apps.alerts.serializers import (
    AlertRuleSerializer,
    AlertSuppressionSerializer,
    NotificationSerializer,
)
from apps.common.permissions import IsTeamMember, RolePermission
from apps.websites.models import Website


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


class AlertSuppressionListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/websites/<website_pk>/alert-suppressions/"""

    serializer_class = AlertSuppressionSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _website(self):
        team = self.request.user.active_team
        return Website.objects.filter(pk=self.kwargs["website_pk"], team=team).first()

    def get_queryset(self):
        website = self._website()
        if website is None:
            return AlertSuppression.objects.none()
        return AlertSuppression.objects.filter(website=website)

    def perform_create(self, serializer):
        website = self._website()
        if website is None:
            from rest_framework.exceptions import NotFound
            raise NotFound("Website not found.")
        serializer.save(website=website, created_by=self.request.user)


class AlertSuppressionDeleteView(generics.DestroyAPIView):
    """DELETE /api/v1/alert-suppressions/<pk>/"""

    serializer_class = AlertSuppressionSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return AlertSuppression.objects.none()
        return AlertSuppression.objects.filter(website__team=team)


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
