from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.site_health.models import (
    PhpError,
    SecurityHeaderReport,
    SeoReport,
    SiteEvent,
    SiteScanState,
    VulnerabilityReport,
)


class PhpErrorSerializer(BaseModelSerializer):
    class Meta:
        model = PhpError
        fields = ("id", "level", "message", "file", "line", "url", "captured_at")
        read_only_fields = fields


class SeoReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeoReport
        fields = (
            "last_checked_at", "check_status", "error",
            "robots_status", "robots_blocks_all", "robots_content",
            "sitemap_status", "sitemap_url", "sitemap_url_count", "sitemap_pages",
            "homepage_indexable", "pages_checked", "noindex_count",
            "meta_title", "meta_description", "h1", "canonical_url", "schema_types",
        )


class SecurityHeaderReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityHeaderReport
        fields = (
            "last_checked_at", "check_status", "error",
            "final_url", "status_code",
            "score", "grade", "headers",
            "pass_count", "warn_count", "fail_count",
        )


class SiteEventSerializer(BaseModelSerializer):
    class Meta:
        model = SiteEvent
        fields = (
            "id", "event_type", "summary", "details", "actor", "severity",
            "occurred_at", "created_at",
            # WP Connect attribution. Optional on the frontend side: it
            # deploys separately, so a frontend that ships first must render.
            "source", "category", "actor_ip", "actor_wp_id",
            "object_type", "object_id",
        )
        read_only_fields = ("id", "created_at")


class VulnerabilityReportSerializer(BaseModelSerializer):
    class Meta:
        model = VulnerabilityReport
        fields = (
            "id", "component_type", "component_name", "component_version",
            "cve_ids", "severity", "title", "description",
            "fixed_in_version", "source", "references", "created_at",
        )
        read_only_fields = fields


class SiteScanStateSerializer(BaseModelSerializer):
    class Meta:
        model = SiteScanState
        fields = (
            "last_scanned_at", "scan_status", "wp_version",
            "wp_latest_version", "wp_update_available",
            "plugins_detected", "error",
        )
        read_only_fields = fields


class PhpErrorIngestSerializer(serializers.Serializer):
    site_id = serializers.CharField(max_length=64)
    errors = serializers.ListField(
        child=serializers.DictField(), default=list, max_length=50
    )


class SiteEventCreateSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=SiteEvent.EventType.values)
    summary = serializers.CharField(max_length=500)
    details = serializers.DictField(default=dict)
    actor = serializers.CharField(max_length=200, allow_blank=True, default="")
    severity = serializers.ChoiceField(
        choices=SiteEvent.Severity.values, default=SiteEvent.Severity.INFO
    )
    occurred_at = serializers.DateTimeField(required=False)


class WpActivityEventSerializer(serializers.Serializer):
    """One buffered event as the snippet reports it.

    The wire field names are a contract with pasted PHP that we cannot redeploy,
    so they stay short and stable rather than mirroring the model.
    """

    seq = serializers.IntegerField(min_value=1)
    type = serializers.CharField(max_length=40)
    occurred_at = serializers.DateTimeField()
    summary = serializers.CharField(max_length=500, allow_blank=True)
    actor_login = serializers.CharField(
        max_length=200, allow_blank=True, required=False, default=""
    )
    actor_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    actor_ip = serializers.IPAddressField(required=False, allow_null=True, default=None)
    object_type = serializers.CharField(
        max_length=30, allow_blank=True, required=False, default=""
    )
    object_id = serializers.CharField(
        max_length=200, allow_blank=True, required=False, default=""
    )
    details = serializers.JSONField(required=False, default=dict)


class WpManifestSliceSerializer(serializers.Serializer):
    walk_id = serializers.CharField(max_length=64)
    entries = serializers.DictField(child=serializers.CharField(max_length=64))
    complete = serializers.BooleanField(default=False)


class WpHeartbeatSerializer(serializers.Serializer):
    """The snippet's 5-minute heartbeat: its own fetch of the homepage.

    Either field is null when the loopback failed at the transport level (the
    host refuses loopback connections, a DNS quirk) — the heartbeat itself is
    still evidence that WordPress is running.
    """

    loopback_status = serializers.IntegerField(
        min_value=100, max_value=599, required=False, allow_null=True, default=None
    )
    loopback_ms = serializers.IntegerField(
        min_value=0, max_value=600_000, required=False, allow_null=True, default=None
    )


class WpActivityIngestSerializer(serializers.Serializer):
    snippet_version = serializers.IntegerField(min_value=1)
    events = WpActivityEventSerializer(many=True, required=False, default=list)
    manifest = WpManifestSliceSerializer(required=False, allow_null=True, default=None)
    heartbeat = WpHeartbeatSerializer(required=False, allow_null=True, default=None)
