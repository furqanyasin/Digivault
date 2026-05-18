from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.mixins import TeamScopedMixin
from apps.common.permissions import IsTeamMember
from apps.monitors.models import Monitor, MonitorCheck, MonitorNotificationRule, NotificationChannel
from apps.monitors.serializers import (
    MonitorCheckSerializer,
    MonitorNotificationRuleSerializer,
    MonitorSerializer,
    NotificationChannelSerializer,
)
from apps.monitors.tasks import check_single_monitor


class MonitorListCreateView(TeamScopedMixin, generics.ListCreateAPIView):
    """GET /api/v1/monitors/  POST /api/v1/monitors/"""

    queryset = Monitor.objects.all()
    serializer_class = MonitorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def perform_create(self, serializer):
        serializer.save(team=self.request.user.active_team)


class MonitorDetailView(TeamScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/monitors/<pk>/"""

    queryset = Monitor.objects.all()
    serializer_class = MonitorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]


class MonitorCheckListView(generics.ListAPIView):
    """GET /api/v1/monitors/<monitor_pk>/checks/"""

    serializer_class = MonitorCheckSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return MonitorCheck.objects.none()
        return MonitorCheck.objects.filter(
            monitor__team=team,
            monitor_id=self.kwargs["monitor_pk"],
        ).order_by("-checked_at")[:200]


class MonitorPauseView(APIView):
    """POST /api/v1/monitors/<pk>/pause/"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        try:
            monitor = Monitor.objects.get(pk=pk, team=team)
        except Monitor.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        Monitor.objects.filter(pk=pk).update(status=Monitor.Status.PAUSED, is_active=False)
        monitor.refresh_from_db()
        return Response(MonitorSerializer(monitor).data)


class MonitorResumeView(APIView):
    """POST /api/v1/monitors/<pk>/resume/"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        try:
            monitor = Monitor.objects.get(pk=pk, team=team)
        except Monitor.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        Monitor.objects.filter(pk=pk).update(status=Monitor.Status.PENDING, is_active=True)
        monitor.refresh_from_db()
        return Response(MonitorSerializer(monitor).data)


class MonitorCheckNowView(APIView):
    """POST /api/v1/monitors/<pk>/check-now/

    Runs the check synchronously so it works without Celery in development.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        from apps.monitors.checker import run_check
        from apps.monitors.notifications import notify_status_change
        from django.utils import timezone

        team = request.user.active_team
        try:
            monitor = Monitor.objects.get(pk=pk, team=team)
        except Monitor.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        previous_status = monitor.status
        try:
            result = run_check(monitor)
        except Exception as exc:
            result = {"status": "down", "response_time_ms": None, "status_code": None, "error_message": str(exc)[:300]}

        new_status = result["status"]
        MonitorCheck.objects.create(
            monitor=monitor,
            status=new_status,
            response_time_ms=result.get("response_time_ms"),
            status_code=result.get("status_code"),
            error_message=result.get("error_message", ""),
        )
        Monitor.objects.filter(pk=monitor.pk).update(
            status=new_status,
            last_checked_at=timezone.now(),
            last_response_time=result.get("response_time_ms"),
        )
        monitor.refresh_from_db()
        monitor.recalculate_uptime()

        if previous_status != new_status and previous_status != "pending":
            try:
                notify_status_change(monitor, previous_status, new_status)
            except Exception:
                pass

        return Response(MonitorSerializer(monitor).data)


# ------------------------------------------------------------------
# Notification channels
# ------------------------------------------------------------------

class NotificationChannelListCreateView(TeamScopedMixin, generics.ListCreateAPIView):
    """GET /api/v1/notification-channels/  POST /api/v1/notification-channels/"""

    queryset = NotificationChannel.objects.all()
    serializer_class = NotificationChannelSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return NotificationChannel.objects.none()
        return NotificationChannel.objects.filter(team=team)

    def perform_create(self, serializer):
        serializer.save(team=self.request.user.active_team)


class NotificationChannelDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/notification-channels/<pk>/"""

    serializer_class = NotificationChannelSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return NotificationChannel.objects.none()
        return NotificationChannel.objects.filter(team=team)


# ------------------------------------------------------------------
# Monitor notification rules
# ------------------------------------------------------------------

class MonitorNotificationRuleListCreateView(generics.ListCreateAPIView):
    """GET /api/v1/monitors/<monitor_pk>/notification-rules/
    POST /api/v1/monitors/<monitor_pk>/notification-rules/
    """

    serializer_class = MonitorNotificationRuleSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return MonitorNotificationRule.objects.none()
        return MonitorNotificationRule.objects.filter(
            monitor__team=team,
            monitor_id=self.kwargs["monitor_pk"],
        ).select_related("channel")

    def perform_create(self, serializer):
        team = self.request.user.active_team
        monitor = Monitor.objects.get(pk=self.kwargs["monitor_pk"], team=team)
        channel = NotificationChannel.objects.get(
            pk=serializer.validated_data.pop("channel_id"), team=team
        )
        serializer.save(monitor=monitor, channel=channel)


class MonitorNotificationRuleDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/monitors/<monitor_pk>/notification-rules/<pk>/"""

    serializer_class = MonitorNotificationRuleSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return MonitorNotificationRule.objects.none()
        return MonitorNotificationRule.objects.filter(
            monitor__team=team,
            monitor_id=self.kwargs["monitor_pk"],
        ).select_related("channel")
