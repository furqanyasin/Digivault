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
    name = serializers.CharField(max_length=200, allow_blank=False)
    hosting_renewal_date = BlankableDateField(required=False, allow_null=True)
    domain_renewal_date = BlankableDateField(required=False, allow_null=True)
    departments = serializers.ListField(
        child=serializers.ChoiceField(choices=Client.DEPARTMENTS),
        required=False,
        default=list,
    )

    class Meta:
        model = Client
        fields = (
            "id", "name", "website_url", "domain", "status", "tier",
            "hosting_platform", "hosting_platform_other",
            "hosting_renewal_date", "domain_renewal_date",
            "domain_access_location", "website_access_level",
            "departments", "running_ppc_ads",
            "website_built_by_digi", "website_maintained_by_digi",
            "notes", "notify_desktop", "notify_email",
            "assigned_to", "monthly_revenue",
            "assigned_websites_count",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "domain", "assigned_websites_count",
            "created_at", "updated_at",
        )

    def get_assigned_websites_count(self, obj) -> int:
        return obj.websites.count()


class ClientLookupSerializer(serializers.Serializer):
    """Compact answer card returned by the /search/ endpoint."""
    id = serializers.UUIDField()
    name = serializers.CharField()
    website_url = serializers.CharField()
    status = serializers.CharField()
    tier = serializers.CharField()
    hosting_platform = serializers.CharField()
    hosting_platform_other = serializers.CharField()
    domain_access_location = serializers.CharField()
    website_access_level = serializers.CharField()
    running_ppc_ads = serializers.CharField()
    website_built_by_digi = serializers.CharField()
    website_maintained_by_digi = serializers.CharField()
    hosting_renewal_date = serializers.DateField(allow_null=True)
    domain_renewal_date = serializers.DateField(allow_null=True)
    notes = serializers.CharField()
    has_access = serializers.SerializerMethodField()
    access_summary = serializers.SerializerMethodField()

    def get_has_access(self, obj) -> bool:
        return bool(obj.domain_access_location and obj.status == "active")

    def get_access_summary(self, obj) -> str:
        if obj.status != "active":
            return f"Client is {obj.status}."
        if obj.domain_access_location:
            return f"Yes — access via {obj.domain_access_location}"
        return "No access location recorded."
