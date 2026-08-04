from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.domains.models import DomainInfo


class DomainInfoSerializer(BaseModelSerializer):
    domain_days_until_expiry = serializers.ReadOnlyField()
    ssl_days_until_expiry = serializers.ReadOnlyField()
    hosting_days_until_expiry = serializers.ReadOnlyField()

    class Meta:
        model = DomainInfo
        fields = (
            "id",
            "registrar",
            "registered_at",
            "expires_at",
            "domain_days_until_expiry",
            "nameservers",
            "whois_privacy",
            "auto_renew",
            "hosting_provider",
            "hosting_ip",
            "server_location",
            "uses_cloudflare",
            "hosting_expires_at",
            "hosting_days_until_expiry",
            "smtp_status",
            "mx_hosts",
            "smtp_checked_at",
            "spf_status",
            "spf_record",
            "dmarc_status",
            "dmarc_record",
            "dkim_status",
            "dkim_selector",
            "ssl_issuer",
            "ssl_expires_at",
            "ssl_days_until_expiry",
            "ssl_auto_renew",
            "last_checked_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

