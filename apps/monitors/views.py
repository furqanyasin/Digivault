import json
import urllib.request

from django.conf import settings
from django.core.mail import send_mail
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import ActivityLog
from apps.audit.services import AuditService
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

    def get_queryset(self):
        qs = super().get_queryset()
        website_id = self.request.query_params.get("website", "").strip()
        if website_id:
            qs = qs.filter(website_id=website_id)
        return qs

    def perform_create(self, serializer):
        monitor = serializer.save(team=self.request.user.active_team)
        AuditService.log_request(
            self.request, ActivityLog.Action.MONITOR_CREATED,
            description=f"Created {monitor.monitor_type} monitor '{monitor.name}'",
            resource_type="monitor", resource_id=monitor.pk,
        )


class MonitorDetailView(TeamScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/monitors/<pk>/"""

    queryset = Monitor.objects.all()
    serializer_class = MonitorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def perform_update(self, serializer):
        monitor = serializer.save()
        AuditService.log_request(
            self.request, ActivityLog.Action.MONITOR_UPDATED,
            description=f"Updated monitor '{monitor.name}'",
            resource_type="monitor", resource_id=monitor.pk,
        )

    def perform_destroy(self, instance):
        AuditService.log_request(
            self.request, ActivityLog.Action.MONITOR_DELETED,
            description=f"Deleted monitor '{instance.name}'",
            resource_type="monitor", resource_id=instance.pk,
        )
        instance.delete()


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


class UptimeTrendView(APIView):
    """GET /api/v1/monitors/uptime-trend/?days=14

    One team-wide uptime percentage per day, for the dashboard sparkline.
    Aggregated from MonitorCheck rather than the cached uptime_* fields, which
    only hold rolling 24h/7d/30d figures and so cannot draw a curve.

    A day with no checks returns `null`, never 0 or 100: no data means we were
    blind, and inventing either number would draw a cliff or a clean run that
    never happened.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    DEFAULT_DAYS = 14
    MAX_DAYS = 90

    def get(self, request):
        from datetime import timedelta

        from django.db.models import Count, Q
        from django.db.models.functions import TruncDate
        from django.utils import timezone

        try:
            days = int(request.query_params.get("days", self.DEFAULT_DAYS))
        except (TypeError, ValueError):
            days = self.DEFAULT_DAYS
        days = max(1, min(days, self.MAX_DAYS))

        team = request.user.active_team
        today = timezone.localdate()
        first_day = today - timedelta(days=days - 1)

        by_day: dict[str, float] = {}
        if team is not None:
            rows = (
                MonitorCheck.objects.filter(
                    monitor__team=team, checked_at__date__gte=first_day
                )
                .annotate(day=TruncDate("checked_at"))
                .values("day")
                .annotate(
                    total=Count("id"),
                    up=Count("id", filter=Q(status=MonitorCheck.Status.UP)),
                )
                .order_by("day")
            )
            for row in rows:
                if row["total"]:
                    by_day[row["day"].isoformat()] = round(
                        row["up"] * 100.0 / row["total"], 2
                    )

        points = []
        for offset in range(days):
            day = (first_day + timedelta(days=offset)).isoformat()
            points.append({"date": day, "value": by_day.get(day)})

        return Response({"days": days, "points": points})


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
        AuditService.log_request(
            request, ActivityLog.Action.MONITOR_PAUSED,
            description=f"Paused monitor '{monitor.name}'",
            resource_type="monitor", resource_id=monitor.pk,
        )
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
        AuditService.log_request(
            request, ActivityLog.Action.MONITOR_RESUMED,
            description=f"Resumed monitor '{monitor.name}'",
            resource_type="monitor", resource_id=monitor.pk,
        )
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
        channel = serializer.save(team=self.request.user.active_team)
        AuditService.log_request(
            self.request, ActivityLog.Action.NOTIFICATION_CHANNEL_CREATED,
            description=f"Created {channel.channel_type} notification channel",
            resource_type="notification_channel", resource_id=channel.pk,
        )


class NotificationChannelDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/notification-channels/<pk>/"""

    serializer_class = NotificationChannelSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return NotificationChannel.objects.none()
        return NotificationChannel.objects.filter(team=team)

    def perform_destroy(self, instance):
        AuditService.log_request(
            self.request, ActivityLog.Action.NOTIFICATION_CHANNEL_DELETED,
            description=f"Deleted {instance.channel_type} notification channel",
            resource_type="notification_channel", resource_id=instance.pk,
        )
        instance.delete()


class NotificationChannelTestView(APIView):
    """POST /api/v1/notification-channels/<pk>/test/ — send a test payload through the channel."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        if not team:
            return Response({"success": False, "message": "No active team."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            channel = NotificationChannel.objects.get(pk=pk, team=team)
        except NotificationChannel.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        ok, message = _test_channel(channel)
        return Response({"success": ok, "message": message})


def _test_channel(channel) -> tuple[bool, str]:
    if channel.channel_type == "email":
        return _test_email(channel)
    if channel.channel_type == "clickup":
        return _test_clickup(channel)
    if channel.channel_type == "slack":
        return _test_slack(channel)
    return False, f"Unknown channel type: {channel.channel_type}"


def _test_slack(channel) -> tuple[bool, str]:
    webhook_url = channel.config.get("webhook_url", "")
    if not webhook_url:
        return False, "Missing webhook_url in config."
    payload = {"text": "[Digivault] Test notification — your Slack alerts are working."}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return True, "Test message sent to Slack."
            return False, f"Slack returned HTTP {resp.status}."
    except Exception as e:
        return False, str(e)


def _test_email(channel) -> tuple[bool, str]:
    addresses = channel.config.get("addresses", [])
    if not addresses:
        return False, "No email addresses configured."
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "alerts@digivault.digilatics.co")
    try:
        send_mail(
            subject="[Digivault] Test notification",
            message="This is a test notification from Digivault. Your email alerts are working correctly.",
            from_email=from_email,
            recipient_list=addresses,
            fail_silently=False,
        )
        return True, f"Test email sent to {', '.join(addresses)}"
    except Exception as e:
        return False, str(e)


def _test_clickup(channel) -> tuple[bool, str]:
    api_token = channel.config.get("api_token", "")
    task_id = channel.config.get("task_id", "")
    if not api_token or not task_id:
        return False, "Missing api_token or task_id in config."
    url = f"https://api.clickup.com/api/v2/task/{task_id}"
    req = urllib.request.Request(url, headers={"Authorization": api_token})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return True, f"ClickUp task '{task_id}' verified successfully."
            return False, f"ClickUp returned HTTP {resp.status}."
    except Exception as e:
        return False, str(e)


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
        rule = serializer.save(monitor=monitor, channel=channel)
        AuditService.log_request(
            self.request, ActivityLog.Action.MONITOR_RULE_CREATED,
            description=f"Added notification rule to monitor '{monitor.name}'",
            resource_type="monitor", resource_id=monitor.pk,
        )


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

    def perform_destroy(self, instance):
        AuditService.log_request(
            self.request, ActivityLog.Action.MONITOR_RULE_DELETED,
            description=f"Removed notification rule from monitor '{instance.monitor.name}'",
            resource_type="monitor", resource_id=instance.monitor_id,
        )
        instance.delete()
