from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.monitors.serializers import MonitorSerializer
from apps.status_pages.models import StatusPage, StatusPageMonitor


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
    overall_status = serializers.CharField()
    monitors = PublicStatusPageMonitorSerializer(many=True)
    updated_at = serializers.DateTimeField()
