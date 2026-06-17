from rest_framework import serializers

from apps.clients.models import Client
from apps.common.serializers import BaseModelSerializer


class BlankableDateField(serializers.DateField):
    """A DateField that treats an empty string as null.

    HTML <input type="date"> submits "" when cleared; DRF's DateField would
    otherwise reject it with "Date has wrong format" and fail the whole save.
    """

    def to_internal_value(self, value):
        if value in ("", None):
            return None
        return super().to_internal_value(value)


class ClientSerializer(BaseModelSerializer):
    domain = serializers.CharField(read_only=True)
    assigned_websites_count = serializers.SerializerMethodField()
    hosting_renewal_date = BlankableDateField(required=False, allow_null=True)
    contract_renewal_date = BlankableDateField(required=False, allow_null=True)

    class Meta:
        model = Client
        fields = (
            "id", "name", "website_url", "domain", "status",
            "hosting_platform", "hosting_renewal_date",
            "domain_access_location", "migration_status",
            "csm_migration_confirmation", "running_ppc_ads",
            "website_built_by_digi", "website_maintained_by_digi",
            "notes", "comments",
            "assigned_to", "monthly_revenue", "support_tier",
            "contract_renewal_date", "assigned_websites_count",
            "clickup_task_id", "clickup_synced_at",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "domain", "assigned_websites_count",
            "clickup_synced_at", "created_at", "updated_at",
        )

    def get_assigned_websites_count(self, obj) -> int:
        return obj.websites.count()


class ClientLookupSerializer(serializers.Serializer):
    """Compact answer card returned by the /search/ endpoint."""
    id = serializers.UUIDField()
    name = serializers.CharField()
    website_url = serializers.CharField()
    status = serializers.CharField()
    hosting_platform = serializers.CharField()
    domain_access_location = serializers.CharField()
    running_ppc_ads = serializers.CharField()
    website_built_by_digi = serializers.CharField()
    website_maintained_by_digi = serializers.CharField()
    migration_status = serializers.CharField()
    csm_migration_confirmation = serializers.CharField()
    hosting_renewal_date = serializers.DateField(allow_null=True)
    comments = serializers.CharField()
    notes = serializers.CharField()
    has_access = serializers.SerializerMethodField()
    access_summary = serializers.SerializerMethodField()

    def get_has_access(self, obj) -> bool:
        return bool(obj.domain_access_location and obj.status == "active")

    def get_access_summary(self, obj) -> str:
        if obj.status == "inactive":
            return "Client is inactive."
        if obj.domain_access_location:
            return f"Yes — access via {obj.domain_access_location}"
        return "No access location recorded."
