from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.websites.models import Website


class WebsiteSerializer(BaseModelSerializer):
    snippet_html = serializers.ReadOnlyField()
    script_count = serializers.SerializerMethodField()
    unknown_script_count = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()

    class Meta:
        model = Website
        fields = (
            "id",
            "name",
            "domain",
            "platform",
            "site_id",
            "status",
            "notes",
            "tags",
            "last_seen_at",
            "snippet_html",
            "script_count",
            "unknown_script_count",
            "client",
            "client_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "site_id", "last_seen_at", "created_at", "updated_at")

    def get_script_count(self, obj) -> int:
        return getattr(obj, "script_count", 0)

    def get_unknown_script_count(self, obj) -> int:
        return getattr(obj, "unknown_script_count", 0)

    def get_client_name(self, obj) -> str | None:
        return obj.client.name if obj.client_id else None


class WebsiteCreateSerializer(BaseModelSerializer):
    class Meta:
        model = Website
        fields = ("id", "name", "domain", "platform", "notes", "tags", "client")
        read_only_fields = ("id",)


class SnippetInstructionSerializer(serializers.Serializer):
    platform = serializers.CharField()
    instruction = serializers.CharField()
    snippet = serializers.CharField()
