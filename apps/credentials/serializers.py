from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.credentials.models import Credential, CredentialAccessLog, CredentialShare


class CredentialSerializer(BaseModelSerializer):
    """Safe list serializer — never returns encrypted fields."""

    website_id = serializers.SerializerMethodField()
    website_name = serializers.SerializerMethodField()

    class Meta:
        model = Credential
        fields = (
            "id",
            "website_id",
            "website_name",
            "label",
            "credential_type",
            "login_url",
            "created_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "website_id", "website_name", "created_by_id", "created_at", "updated_at")

    def get_website_id(self, obj) -> str | None:
        return str(obj.website.id) if obj.website_id else None

    def get_website_name(self, obj) -> str | None:
        if obj.website:
            return obj.website.name or obj.website.domain
        return None


class CredentialWriteSerializer(serializers.Serializer):
    """Accepts plaintext fields for create/update — never stored in plain form."""

    label = serializers.CharField(max_length=200)
    credential_type = serializers.ChoiceField(choices=Credential.CredentialType.values)
    login_url = serializers.URLField(max_length=500, allow_blank=True, default="")
    username = serializers.CharField(max_length=500, allow_blank=True, default="")
    password = serializers.CharField(
        max_length=500, allow_blank=True, default="", write_only=True
    )
    notes = serializers.CharField(max_length=2000, allow_blank=True, default="")
    website_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class RevealedCredentialSerializer(serializers.Serializer):
    """Returned by the reveal endpoint — plaintext, short-lived."""

    username = serializers.CharField()
    password = serializers.CharField()
    notes = serializers.CharField()


class CredentialAccessLogSerializer(BaseModelSerializer):
    user_email = serializers.SerializerMethodField()

    class Meta:
        model = CredentialAccessLog
        fields = ("id", "user_email", "action", "ip_address", "created_at")
        read_only_fields = fields

    def get_user_email(self, obj) -> str:
        return obj.user.email


class CredentialShareSerializer(BaseModelSerializer):
    user_id = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    shared_by_email = serializers.SerializerMethodField()

    class Meta:
        model = CredentialShare
        fields = ("id", "user_id", "email", "name", "role",
                  "shared_by_email", "created_at")
        read_only_fields = fields

    def get_user_id(self, obj) -> str:
        return str(obj.user_id)

    def get_email(self, obj) -> str:
        return obj.user.email

    def get_name(self, obj) -> str:
        first = obj.user.first_name or ""
        last = obj.user.last_name or ""
        return (first + " " + last).strip() or obj.user.email

    def get_role(self, obj) -> str:
        from apps.accounts.models import TeamMembership
        m = TeamMembership.objects.filter(
            user=obj.user, team=obj.credential.team
        ).first()
        return m.role if m else "developer"

    def get_shared_by_email(self, obj) -> str | None:
        return obj.shared_by.email if obj.shared_by else None


class CredentialShareWriteSerializer(serializers.Serializer):
    user_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False
    )
