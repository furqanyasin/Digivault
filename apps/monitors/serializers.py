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
    block_info = serializers.SerializerMethodField()

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
            "block_info",
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

    def get_block_info(self, obj) -> dict | None:
        """What is blocking us, and where to go to fix it.

        Only present while the monitor is actually blocked. "Blocked" is a state
        the agency can clear in about thirty seconds — but only if the UI says
        who is doing the blocking and hands over the allowlist rule, rather than
        leaving a mystery amber badge on the card.
        """
        if obj.status != Monitor.Status.BLOCKED:
            return None

        latest = (
            obj.checks.filter(status=MonitorCheck.Status.BLOCKED)
            .order_by("-checked_at")
            .first()
        )
        if latest is None:
            return None

        # How long we have been unable to see the site: the oldest blocked check
        # in the unbroken run of them ending now.
        since = latest.checked_at
        for check in obj.checks.order_by("-checked_at")[:50]:
            if check.status != MonitorCheck.Status.BLOCKED:
                break
            since = check.checked_at

        return {
            "message": latest.error_message,
            "since": since,
            "consecutive_blocks": obj.consecutive_blocks,
            "help_url": "https://digivault.digilatics.co/bot",
        }
