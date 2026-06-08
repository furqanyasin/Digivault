from rest_framework import serializers

from apps.alerts.models import AlertRule, AlertSuppression, Notification
from apps.common.serializers import BaseModelSerializer


class AlertSuppressionSerializer(BaseModelSerializer):
    class Meta:
        model = AlertSuppression
        fields = (
            "id",
            "match_type",
            "match_value",
            "reason",
            "created_at",
        )
        read_only_fields = ("id", "created_at")


class AlertRuleSerializer(BaseModelSerializer):
    class Meta:
        model = AlertRule
        fields = (
            "id",
            "website",
            "channel",
            "min_severity",
            "change_types",
            "delivery_mode",
            "slack_webhook_url",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
        extra_kwargs = {
            "slack_webhook_url": {"write_only": True},
        }


class NotificationSerializer(BaseModelSerializer):
    website_name = serializers.SerializerMethodField()
    change_description = serializers.SerializerMethodField()
    change_severity = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = (
            "id",
            "website",
            "website_name",
            "channel",
            "delivery_status",
            "delivered_at",
            "change_description",
            "change_severity",
            "read",
            "read_at",
            "created_at",
        )
        read_only_fields = fields

    def get_website_name(self, obj) -> str:
        return obj.website.name if obj.website_id else ""

    def get_change_description(self, obj) -> str:
        return obj.script_change.description if obj.script_change_id else ""

    def get_change_severity(self, obj) -> str:
        return obj.script_change.severity if obj.script_change_id else ""
