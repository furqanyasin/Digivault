from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.monitors.models import Monitor, MonitorCheck, MonitorNotificationRule, NotificationChannel


class NotificationChannelSerializer(BaseModelSerializer):
    class Meta:
        model = NotificationChannel
        fields = ("id", "name", "channel_type", "config", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class MonitorNotificationRuleSerializer(BaseModelSerializer):
    channel = NotificationChannelSerializer(read_only=True)
    channel_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = MonitorNotificationRule
        fields = (
            "id", "monitor", "channel", "channel_id",
            "notify_on_down", "notify_on_recovery", "notify_on_degraded",
            "created_at",
        )
        read_only_fields = ("id", "monitor", "created_at")


class MonitorCheckSerializer(BaseModelSerializer):
    class Meta:
        model = MonitorCheck
        fields = (
            "id",
            "status",
            "response_time_ms",
            "status_code",
            "error_message",
            "checked_at",
        )
        read_only_fields = fields


class MonitorSerializer(BaseModelSerializer):
    recent_statuses = serializers.SerializerMethodField()

    class Meta:
        model = Monitor
        fields = (
            "id",
            "name",
            "url",
            "monitor_type",
            "expected_status_code",
            "request_method",
            "request_headers",
            "keyword",
            "port",
            "check_interval",
            "timeout",
            "retry_count",
            "status",
            "is_active",
            "last_checked_at",
            "last_response_time",
            "uptime_24h",
            "uptime_7d",
            "uptime_30d",
            "recent_statuses",
            "tags",
            "notes",
            "website",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "status",
            "last_checked_at",
            "last_response_time",
            "uptime_24h",
            "uptime_7d",
            "uptime_30d",
            "recent_statuses",
            "created_at",
            "updated_at",
        )

    def get_recent_statuses(self, obj) -> list[str]:
        qs = obj.checks.order_by("-checked_at")[:20]
        return [c.status for c in reversed(list(qs))]
