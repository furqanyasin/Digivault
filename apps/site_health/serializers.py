from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.site_health.models import PhpError, SiteEvent, SiteScanState, VulnerabilityReport


class PhpErrorSerializer(BaseModelSerializer):
    class Meta:
        model = PhpError
        fields = ("id", "level", "message", "file", "line", "url", "captured_at")
        read_only_fields = fields


class SiteEventSerializer(BaseModelSerializer):
    class Meta:
        model = SiteEvent
        fields = ("id", "event_type", "summary", "details", "actor", "severity", "occurred_at", "created_at")
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
        fields = ("last_scanned_at", "scan_status", "wp_version", "plugins_detected", "error")
        read_only_fields = fields


class PhpErrorIngestSerializer(serializers.Serializer):
    site_id = serializers.CharField(max_length=64)
    errors = serializers.ListField(child=serializers.DictField(), default=list)


class SiteEventCreateSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=SiteEvent.EventType.values)
    summary = serializers.CharField(max_length=500)
    details = serializers.DictField(default=dict)
    actor = serializers.CharField(max_length=200, allow_blank=True, default="")
    severity = serializers.ChoiceField(
        choices=SiteEvent.Severity.values, default=SiteEvent.Severity.INFO
    )
    occurred_at = serializers.DateTimeField(required=False)
