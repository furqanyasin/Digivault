from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.websites.models import Website
from apps.websites.wp_sso_snippet import SNIPPET_VERSION

# Matches the snippet's own dead-man switch: after this long with no accepted
# flush the snippet has stopped collecting, so the dashboard must stop
# implying the site is reporting.
_SNIPPET_STALE_DAYS = 7


class WebsiteSerializer(BaseModelSerializer):
    snippet_html = serializers.ReadOnlyField()
    script_count = serializers.SerializerMethodField()
    unknown_script_count = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    client_hosting_renewal_date = serializers.SerializerMethodField()
    notification_channel_name = serializers.SerializerMethodField()
    uptime_notification_channel_name = serializers.SerializerMethodField()
    # Never expose the secret itself — only whether SSO is set up.
    wp_sso_configured = serializers.SerializerMethodField()
    status_page = serializers.SerializerMethodField()
    uptime_30d = serializers.SerializerMethodField()
    ssl_days_until_expiry = serializers.SerializerMethodField()
    wp_connect_status = serializers.SerializerMethodField()
    snippet_status = serializers.SerializerMethodField()

    class Meta:
        model = Website
        fields = (
            "id",
            "name",
            "domain",
            "platform",
            "site_id",
            "status",
            "health_score",
            # Writable — VIP is a user setting, not derived state.
            "is_vip",
            # Writable — behaviour analytics is opt-in per site, and this is
            # the switch. Off means the ingest answers 204 and stores nothing.
            "heatmap_enabled",
            "notes",
            "tags",
            "last_seen_at",
            "snippet_status",
            "snippet_first_seen_at",
            "snippet_last_seen_at",
            "snippet_html",
            "script_count",
            "unknown_script_count",
            "client",
            "client_name",
            "client_hosting_renewal_date",
            "notification_channel",
            "notification_channel_name",
            "uptime_notification_channel",
            "uptime_notification_channel_name",
            "wp_sso_configured",
            "status_page",
            "uptime_30d",
            "ssl_days_until_expiry",
            "wp_connect_version",
            "wp_connect_status",
            # The heartbeat (apps/monitors/evidence.py): when WordPress last
            # reported in, and what it got loading its own homepage.
            "wp_connect_last_ack",
            "wp_connect_loopback_status",
            "wp_connect_loopback_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id", "site_id", "health_score", "last_seen_at", "snippet_status",
            "snippet_first_seen_at", "snippet_last_seen_at", "created_at", "updated_at",
            "wp_connect_last_ack", "wp_connect_loopback_status", "wp_connect_loopback_at",
        )

    def get_script_count(self, obj) -> int:
        return getattr(obj, "script_count", 0)

    def get_unknown_script_count(self, obj) -> int:
        return getattr(obj, "unknown_script_count", 0)

    def get_client_name(self, obj) -> str | None:
        return obj.client.name if obj.client_id else None

    def get_client_hosting_renewal_date(self, obj) -> str | None:
        """The hosting renewal date entered on the owning client.

        Hosting expiry is not discoverable from WHOIS or DNS — a person types it
        — so the client record is the authoritative source, and the website page
        shows this in preference to the mirrored copy on DomainInfo.
        """
        if not obj.client_id or not obj.client.hosting_renewal_date:
            return None
        return obj.client.hosting_renewal_date.isoformat()

    def get_notification_channel_name(self, obj) -> str | None:
        return obj.notification_channel.name if obj.notification_channel_id else None

    def get_uptime_notification_channel_name(self, obj) -> str | None:
        return (
            obj.uptime_notification_channel.name
            if obj.uptime_notification_channel_id
            else None
        )

    def get_wp_sso_configured(self, obj) -> bool:
        return bool(obj.wp_sso_secret)

    def get_wp_connect_status(self, obj) -> str:
        """Where this site sits in the snippet rollout.

        Exists because a re-paste campaign across every client is impossible
        to run without knowing who is still on the old snippet — and nothing
        else user-facing depends on it, so it is the easiest thing to forget.
        """
        from django.utils import timezone
        from django.utils.timezone import timedelta

        if not obj.wp_connect_version or obj.wp_connect_last_ack is None:
            return "absent"
        if obj.wp_connect_last_ack < timezone.now() - timedelta(days=_SNIPPET_STALE_DAYS):
            return "stale"
        if obj.wp_connect_version < SNIPPET_VERSION:
            return "outdated"
        # A v2 paste from before the uptime heartbeat (apps/monitors/evidence.py)
        # reports the same version number, so the heartbeat is what tells the
        # two apart. It is the reason to re-paste on firewall-blocked sites.
        if obj.wp_connect_loopback_at is None:
            return "outdated"
        return "current"

    def get_snippet_status(self, obj) -> str:
        if not obj.snippet_last_seen_at:
            return Website.SnippetStatus.NOT_INSTALLED
        from django.utils import timezone
        from django.utils.timezone import timedelta

        if obj.snippet_last_seen_at < timezone.now() - timedelta(days=_SNIPPET_STALE_DAYS):
            return Website.SnippetStatus.STALE
        return Website.SnippetStatus.INSTALLED

    def get_uptime_30d(self, obj) -> float | None:
        monitor = next(iter(obj.monitors.all()), None)
        return monitor.uptime_30d if monitor else None

    def get_ssl_days_until_expiry(self, obj) -> int | None:
        domain_info = getattr(obj, "domain_info", None)
        return domain_info.ssl_days_until_expiry if domain_info else None

    def _validate_team_channel(self, value):
        if value is None:
            return value
        request = self.context.get("request")
        team = getattr(request.user, "active_team", None) if request else None
        if team is not None and value.team_id != team.id:
            raise serializers.ValidationError("Channel does not belong to your team.")
        return value

    def validate_notification_channel(self, value):
        return self._validate_team_channel(value)

    def validate_uptime_notification_channel(self, value):
        return self._validate_team_channel(value)

    def get_status_page(self, obj) -> dict | None:
        # Only compute on the detail view — avoids an N+1 on the dashboard list.
        view = self.context.get("view")
        if view is not None and getattr(view, "action", None) != "retrieve":
            return None

        from apps.status_pages.models import StatusPage

        sp = (
            StatusPage.objects.filter(monitors__monitor__website=obj)
            .distinct()
            .first()
        )
        if sp is None:
            return None
        return {
            "slug": sp.slug,
            "name": sp.name,
            "status": sp.overall_status,
            "monitor_count": sp.monitors.count(),
        }


class WebsiteCreateSerializer(BaseModelSerializer):
    class Meta:
        model = Website
        fields = ("id", "name", "domain", "platform", "notes", "tags", "client")
        read_only_fields = ("id",)

    def validate_client(self, value):
        """A website may only be attached to a client on the user's active team."""
        if value is None:
            return value
        request = self.context.get("request")
        team = getattr(request.user, "active_team", None) if request else None
        if team is None or value.team_id != team.id:
            raise serializers.ValidationError("Client not found on this team.")
        return value


class SnippetInstructionSerializer(serializers.Serializer):
    platform = serializers.CharField()
    instruction = serializers.CharField()
    snippet = serializers.CharField()
