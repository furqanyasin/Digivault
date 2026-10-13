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
    website_domain = serializers.SerializerMethodField()

    class Meta:
        model = AlertRule
        fields = (
            "id",
            "name",
            "website",
            "website_domain",
            "channel",
            "min_severity",
            "change_types",
            "delivery_mode",
            "slack_webhook_url",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "website_domain", "created_at", "updated_at")
        extra_kwargs = {
            "slack_webhook_url": {"write_only": True},
        }

    def get_website_domain(self, obj) -> str:
        return obj.website.domain if obj.website_id else ""

    def validate_slack_webhook_url(self, value):
        """Refuse a webhook that is not actually a Slack webhook.

        This field is a user-writable URL that the server later fetches, and any
        team member can write it — there is no role gate on creating an alert
        rule. Without a host check that is a plain SSRF sink pointed at whatever
        the writer chooses: cloud metadata, Redis, or this API on localhost.
        Delivery refuses a non-Slack host too; rejecting it here is what makes
        the refusal visible at the moment someone sets it, instead of as a line
        in the worker log the first time an alert fires.
        """
        if not value:
            return value
        from urllib.parse import urlsplit

        from apps.alerts.delivery import SLACK_WEBHOOK_HOSTS

        parts = urlsplit(value)
        if parts.scheme != "https" or (parts.hostname or "").lower() not in SLACK_WEBHOOK_HOSTS:
            raise serializers.ValidationError(
                "Must be an https:// webhook on "
                f"{', '.join(sorted(SLACK_WEBHOOK_HOSTS))}."
            )
        return value

    def validate_website(self, value):
        """A rule may only target a website on the requesting user's active team."""
        if value is None:
            return value
        request = self.context.get("request")
        team = getattr(request.user, "active_team", None) if request else None
        if team is None or value.team_id != team.id:
            raise serializers.ValidationError("Website not found on this team.")
        return value


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
