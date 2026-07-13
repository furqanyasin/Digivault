from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.websites.models import Website


class WebsiteSerializer(BaseModelSerializer):
    snippet_html = serializers.ReadOnlyField()
    script_count = serializers.SerializerMethodField()
    unknown_script_count = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    notification_channel_name = serializers.SerializerMethodField()
    uptime_notification_channel_name = serializers.SerializerMethodField()
    status_page = serializers.SerializerMethodField()

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
            "notes",
            "tags",
            "last_seen_at",
            "snippet_html",
            "script_count",
            "unknown_script_count",
            "client",
            "client_name",
            "notification_channel",
            "notification_channel_name",
            "uptime_notification_channel",
            "uptime_notification_channel_name",
            "status_page",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "site_id", "health_score", "last_seen_at", "created_at", "updated_at")

    def get_script_count(self, obj) -> int:
        return getattr(obj, "script_count", 0)

    def get_unknown_script_count(self, obj) -> int:
        return getattr(obj, "unknown_script_count", 0)

    def get_client_name(self, obj) -> str | None:
        return obj.client.name if obj.client_id else None

    def get_notification_channel_name(self, obj) -> str | None:
        return obj.notification_channel.name if obj.notification_channel_id else None

    def get_uptime_notification_channel_name(self, obj) -> str | None:
        return (
            obj.uptime_notification_channel.name
            if obj.uptime_notification_channel_id
            else None
        )

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


class SnippetInstructionSerializer(serializers.Serializer):
    platform = serializers.CharField()
    instruction = serializers.CharField()
    snippet = serializers.CharField()
