from rest_framework import serializers

from apps.audit.models import ActivityLog


class ActivityLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.SerializerMethodField()
    actor_name = serializers.SerializerMethodField()
    action_label = serializers.SerializerMethodField()
    website_name = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()

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
            "website_name",
            "client_name",
            "description",
            "ip_address",
            "metadata",
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

    @staticmethod
    def website_id_of(log) -> str | None:
        """The website a log line refers to, if any.

        Website-scoped actions record the id either as the resource itself or in
        metadata (script reviews, change acknowledgements) — the same two places
        the ?website_id= filter looks.
        """
        if log.resource_type == "website" and log.resource_id:
            return str(log.resource_id)
        website_id = (log.metadata or {}).get("website_id")
        return str(website_id) if website_id else None

    # Names come from maps the view builds for the whole page — resolving them
    # per row here would be a query per row.
    def get_website_name(self, obj) -> str:
        website_id = self.website_id_of(obj)
        if not website_id:
            return ""
        entry = self.context.get("website_names", {}).get(website_id)
        return entry[0] if entry else ""

    def get_client_name(self, obj) -> str:
        """Only for actions that target a client record.

        Deliberately does NOT fall back to the owning client of a website: the
        two columns are mutually exclusive, so the one that fills tells you what
        the action was actually about. A website edit is a website event, even
        though a client owns the site.
        """
        if obj.resource_type != "client" or not obj.resource_id:
            return ""
        return self.context.get("client_names", {}).get(str(obj.resource_id), "")
