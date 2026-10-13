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
            "checked_via",
            "checked_at",
        )
        read_only_fields = fields


def block_vendor(message: str) -> str:
    """The firewall named in a block message ("Blocked by SiteGround (HTTP 202)…")."""
    import re

    m = re.match(r"Blocked by (.+?) \(HTTP", message or "")
    return m.group(1) if m else "Unknown firewall"


class MonitorSerializer(BaseModelSerializer):
    recent_statuses = serializers.SerializerMethodField()
    block_info = serializers.SerializerMethodField()
    # Who produced the current status when a firewall blocks our own check:
    # "google" (PageSpeed), "site" (the WP Connect heartbeat), "visitors" (the
    # tracking snippet); "" for our own.
    last_checked_via = serializers.SerializerMethodField()

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
            "last_checked_via",
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

    def get_last_checked_via(self, obj) -> str:
        latest = obj.checks.order_by("-checked_at").values_list("checked_via", flat=True).first()
        return latest or ""

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

        # How long we have been unable to see the site, and for how many checks:
        # the unbroken run of blocked checks ending now. Counted from the checks
        # themselves — `consecutive_blocks` is not bumped on every path that
        # records a block, and the card read "blocked on the last 0 checks".
        since = latest.checked_at
        run = 0
        for check in obj.checks.order_by("-checked_at")[:50]:
            if check.status != MonitorCheck.Status.BLOCKED:
                break
            since = check.checked_at
            run += 1

        from apps.monitors import second_opinion

        website = obj.website
        return {
            "message": latest.error_message,
            "vendor": block_vendor(latest.error_message),
            # "firewall": a WAF answered instead of the site. "visitors": our
            # probe failed outright and recent real traffic is why it is not
            # called down (monitors.liveness). The page heading differs: only
            # the second one has evidence the site is serving visitors.
            "reason": "firewall" if (latest.error_message or "").startswith("Blocked by") else "visitors",
            "since": since,
            "consecutive_blocks": max(run, obj.consecutive_blocks),
            "help_url": "https://digivault.digilatics.co/bot",
            # Which evidence could stand in for our check (monitors.evidence),
            # so the page can say what would end the block without a ticket.
            "has_heartbeat": bool(website and website.wp_connect_loopback_at),
            "has_snippet": bool(website and website.snippet_last_seen_at),
            "second_opinion_enabled": second_opinion.enabled(),
        }
