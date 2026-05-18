from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.scripts.models import Script, ScriptChange, ScriptSnapshot


class IngestScriptSerializer(serializers.Serializer):
    """A single script entry within an ingest payload."""

    src = serializers.CharField(max_length=2048, allow_blank=True)
    location = serializers.ChoiceField(
        choices=Script.Location.values, default=Script.Location.UNKNOWN
    )
    is_async = serializers.BooleanField(default=False)
    is_defer = serializers.BooleanField(default=False)
    is_inline = serializers.BooleanField(default=False)
    inline_hash = serializers.CharField(max_length=64, allow_blank=True, default="")
    wp_plugin = serializers.CharField(max_length=200, allow_blank=True, default="")
    wp_post_id = serializers.IntegerField(allow_null=True, default=None)


class IngestPayloadSerializer(serializers.Serializer):
    """Payload posted by the universal JS snippet."""

    site_id = serializers.CharField(max_length=64)
    page_url = serializers.URLField(max_length=2048)
    scripts = IngestScriptSerializer(many=True)
    user_agent = serializers.CharField(max_length=512, allow_blank=True, default="")
    snippet_version = serializers.CharField(max_length=20, allow_blank=True, default="")


class ScriptSerializer(BaseModelSerializer):
    class Meta:
        model = Script
        fields = (
            "id",
            "src_url",
            "src_domain",
            "provider",
            "category",
            "location",
            "scope",
            "is_async",
            "is_defer",
            "is_inline",
            "wp_plugin",
            "seen_on_pages",
            "is_active",
            "review_status",
            "first_seen_at",
            "last_seen_at",
            "created_at",
        )
        read_only_fields = (
            "id", "src_url", "src_domain", "provider", "category", "location",
            "scope", "is_async", "is_defer", "is_inline", "wp_plugin",
            "seen_on_pages", "is_active", "first_seen_at", "last_seen_at", "created_at",
        )


class ScriptChangeSerializer(BaseModelSerializer):
    script = ScriptSerializer(read_only=True)
    is_acknowledged = serializers.ReadOnlyField()

    class Meta:
        model = ScriptChange
        fields = (
            "id",
            "change_type",
            "severity",
            "description",
            "old_value",
            "new_value",
            "script",
            "is_acknowledged",
            "acknowledged_at",
            "acknowledged_by",
            "created_at",
        )
        read_only_fields = fields
