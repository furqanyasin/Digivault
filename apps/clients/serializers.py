from rest_framework import serializers

from apps.clients.models import Client
from apps.common.serializers import BaseModelSerializer


class ClientSerializer(BaseModelSerializer):
    domain = serializers.CharField(read_only=True)

    class Meta:
        model = Client
        fields = (
            "id", "name", "website_url", "domain", "status",
            "hosting_platform", "hosting_renewal_date",
            "domain_access_location", "migration_status",
            "csm_migration_confirmation", "running_ppc_ads",
            "website_built_by_digi", "website_maintained_by_digi",
            "notes", "comments",
            "clickup_task_id", "clickup_synced_at",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "domain", "clickup_synced_at", "created_at", "updated_at")


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
