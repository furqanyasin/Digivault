from rest_framework import serializers

from apps.audit.models import ActivityLog


class ActivityLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.SerializerMethodField()
    actor_name = serializers.SerializerMethodField()
    action_label = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = (
            "id",
            "actor_email",
            "actor_name",
            "action",
            "action_label",
            "resource_type",
            "resource_id",
            "description",
            "ip_address",
            "created_at",
        )

    def get_actor_email(self, obj) -> str:
        return obj.actor.email if obj.actor else "system"

    def get_actor_name(self, obj) -> str:
        if not obj.actor:
            return "System"
        name = f"{obj.actor.first_name} {obj.actor.last_name}".strip()
        return name or obj.actor.email

    def get_action_label(self, obj) -> str:
        return obj.get_action_display()
