from django.db import models
from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.monitors.serializers import MonitorSerializer
from apps.status_pages.models import (
    MaintenanceWindow,
    StatusPage,
    StatusPageIncident,
    StatusPageMonitor,
)


class StatusPageIncidentSerializer(BaseModelSerializer):
    class Meta:
        model = StatusPageIncident
        fields = (
            "id", "title", "body", "status",
            "created_at", "updated_at", "resolved_at",
        )
        read_only_fields = ("id", "created_at", "updated_at", "resolved_at")


class MaintenanceWindowSerializer(BaseModelSerializer):
    is_active = serializers.ReadOnlyField()

    class Meta:
        model = MaintenanceWindow
        fields = (
            "id", "title", "message", "scheduled_start", "scheduled_end",
            "is_active", "created_at",
        )
        read_only_fields = ("id", "is_active", "created_at")


class StatusPageMonitorSerializer(BaseModelSerializer):
    monitor_detail = MonitorSerializer(source="monitor", read_only=True)
    monitor_id = serializers.UUIDField(write_only=True)
    effective_name = serializers.SerializerMethodField()

    class Meta:
        model = StatusPageMonitor
        fields = (
            "id",
            "monitor_id",
            "monitor_detail",
            "display_name",
            "display_order",
            "effective_name",
        )
        read_only_fields = ("id",)

    def get_effective_name(self, obj):
        return obj.display_name or obj.monitor.name


class StatusPageSerializer(BaseModelSerializer):
    overall_status = serializers.CharField(read_only=True)

    class Meta:
        model = StatusPage
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "allow_indexing",
            "logo_url",
            "brand_color",
            "overall_status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "overall_status", "created_at", "updated_at")


class PublicStatusPageMonitorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.SerializerMethodField()
    status = serializers.CharField(source="monitor.status")
    uptime_90d = serializers.SerializerMethodField()
    uptime_bars = serializers.SerializerMethodField()
    last_checked_at = serializers.DateTimeField(source="monitor.last_checked_at")
    last_response_time = serializers.IntegerField(source="monitor.last_response_time")

    def get_name(self, obj):
        return obj.display_name or obj.monitor.name

    def get_uptime_90d(self, obj):
        bars = obj.uptime_bars(90)
        data_bars = [b for b in bars if b["status"] != "no-data"]
        if not data_bars:
            return None
        up_count = sum(1 for b in data_bars if b["status"] == "up")
        return round((up_count / len(data_bars)) * 100, 2)

    def get_uptime_bars(self, obj):
        return obj.uptime_bars(90)


class PublicStatusPageSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.SlugField()
    description = serializers.CharField()
    allow_indexing = serializers.BooleanField()
    logo_url = serializers.CharField()
    brand_color = serializers.CharField()
    overall_status = serializers.CharField()
    monitors = PublicStatusPageMonitorSerializer(many=True)
    incidents = serializers.SerializerMethodField()
    maintenance = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField()

    def get_incidents(self, obj):
        # Unresolved incidents + those resolved within the last 7 days.
        from django.utils import timezone

        cutoff = timezone.now() - timezone.timedelta(days=7)
        qs = obj.incidents.filter(
            models.Q(resolved_at__isnull=True) | models.Q(resolved_at__gte=cutoff)
        )
        return StatusPageIncidentSerializer(qs, many=True).data

    def get_maintenance(self, obj):
        # Active + upcoming maintenance windows.
        from django.utils import timezone

        qs = obj.maintenance_windows.filter(scheduled_end__gte=timezone.now())
        return MaintenanceWindowSerializer(qs, many=True).data
