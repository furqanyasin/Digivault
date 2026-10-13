from rest_framework import serializers

from apps.clients.models import Client
from apps.common.serializers import BaseModelSerializer
from apps.credentials.models import (
    Credential,
    CredentialAccessLog,
    CredentialAccessRequest,
    CredentialPasswordHistory,
    CredentialShare,
    SubTeamCredentialGrant,
    VaultFolder,
    normalize_totp_secret,
)

#: "" is "unfiled". Shared by the credential and group serializers.
DEPARTMENT_CHOICES = ("", *Client.DEPARTMENTS)


class CredentialSerializer(BaseModelSerializer):
    """Safe list serializer — never returns encrypted fields."""

    website_id = serializers.SerializerMethodField()
    website_name = serializers.SerializerMethodField()
    client_id = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    folder_id = serializers.SerializerMethodField()
    folder_name = serializers.SerializerMethodField()
    password_age_days = serializers.ReadOnlyField()
    # Whether an authenticator secret is stored. The secret itself is never
    # serialized anywhere; the code comes from the /totp/ endpoints.
    has_totp = serializers.ReadOnlyField()
    # {at, by_email, note} while someone has reported it not working, else null.
    broken = serializers.SerializerMethodField()

    class Meta:
        model = Credential
        fields = (
            "broken",
            "id",
            "website_id",
            "website_name",
            "client_id",
            "client_name",
            "folder_id",
            "folder_name",
            "department",
            "has_totp",
            "label",
            "credential_type",
            "login_url",
            "created_by_id",
            "last_password_changed_at",
            "password_strength",
            "password_age_days",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id", "website_id", "website_name", "client_id", "client_name",
            "folder_id", "folder_name", "department", "has_totp", "broken", "created_by_id",
            "last_password_changed_at", "password_strength", "password_age_days",
            "created_at", "updated_at",
        )

    def get_website_id(self, obj) -> str | None:
        return str(obj.website.id) if obj.website_id else None

    def get_website_name(self, obj) -> str | None:
        if obj.website:
            return obj.website.name or obj.website.domain
        return None

    def get_broken(self, obj) -> dict | None:
        if not obj.reported_broken_at:
            return None
        return {
            "at": obj.reported_broken_at,
            "by_email": obj.reported_broken_by.email if obj.reported_broken_by_id else None,
            "note": obj.reported_broken_note,
        }

    def get_folder_id(self, obj) -> str | None:
        return str(obj.folder_id) if obj.folder_id else None

    def get_folder_name(self, obj) -> str | None:
        return obj.folder.name if obj.folder_id else None

    def get_client_id(self, obj) -> str | None:
        return str(obj.client_id) if obj.client_id else None

    def get_client_name(self, obj) -> str | None:
        return obj.client.name if obj.client_id else None


class CredentialWriteSerializer(serializers.Serializer):
    """Accepts plaintext fields for create/update — never stored in plain form."""

    label = serializers.CharField(max_length=200)
    credential_type = serializers.ChoiceField(choices=Credential.CredentialType.values)
    login_url = serializers.URLField(max_length=500, allow_blank=True, default="")
    username = serializers.CharField(max_length=500, allow_blank=True, default="")
    password = serializers.CharField(
        max_length=500, allow_blank=True, default="", write_only=True
    )
    # Long enough for a secure note or a pasted SSH key, which live here.
    notes = serializers.CharField(max_length=10000, allow_blank=True, default="")
    website_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    # Absent means "derive it" on create (the website's client, the type's
    # default department) and "leave it" on update; null / "" mean "none".
    client_id = serializers.UUIDField(required=False, allow_null=True)
    # The folder to file it in; absent leaves it, null unfiles it.
    folder_id = serializers.UUIDField(required=False, allow_null=True)
    department = serializers.ChoiceField(choices=DEPARTMENT_CHOICES, required=False)
    # Bare base32 secret or an otpauth:// URI. Absent leaves it, "" removes it.
    totp = serializers.CharField(
        max_length=500, required=False, allow_blank=True, write_only=True
    )

    def validate_totp(self, value: str) -> str:
        try:
            return normalize_totp_secret(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class RevealedCredentialSerializer(serializers.Serializer):
    """Returned by the reveal endpoint — plaintext, short-lived."""

    username = serializers.CharField()
    password = serializers.CharField(allow_blank=True)
    notes = serializers.CharField(allow_blank=True)
    # True when the requester may not view the password (it is blanked above).
    password_hidden = serializers.BooleanField(default=False)


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
                  "shared_by_email", "can_view_password", "expires_at", "created_at")
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
    # Off unless asked for: a share is "can use it"; seeing the password is a
    # separate choice (as it already was for group grants).
    can_view_password = serializers.BooleanField(default=False)
    # Optional: a temporary share. Absent or null = permanent.
    expires_in_hours = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=24 * 90
    )


class RequestableCredentialSerializer(BaseModelSerializer):
    """What the request picker shows of a credential you cannot see."""

    website_name = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()

    class Meta:
        model = Credential
        fields = (
            "id", "label", "credential_type", "website_name", "client_name", "department",
        )
        read_only_fields = fields

    def get_website_name(self, obj) -> str | None:
        return (obj.website.name or obj.website.domain) if obj.website_id else None

    def get_client_name(self, obj) -> str | None:
        return obj.client.name if obj.client_id else None


_DURATIONS = [h for h in CredentialAccessRequest.DURATION_CHOICES if h]


class AccessRequestWriteSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    # One of 4, 24, 168, or null for permanent.
    hours = serializers.ChoiceField(choices=_DURATIONS, required=False, allow_null=True, default=24)


class AccessDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    hours = serializers.ChoiceField(choices=_DURATIONS, required=False, allow_null=True, default=None)
    can_view_password = serializers.BooleanField(required=False, default=False)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class AccessRequestSerializer(BaseModelSerializer):
    credential_id = serializers.UUIDField(source="credential.id", read_only=True)
    credential_label = serializers.CharField(source="credential.label", read_only=True)
    credential_type = serializers.CharField(source="credential.credential_type", read_only=True)
    requester_id = serializers.UUIDField(source="requester.id", read_only=True)
    requester_email = serializers.CharField(source="requester.email", read_only=True)
    requester_name = serializers.SerializerMethodField()
    decided_by_email = serializers.SerializerMethodField()

    class Meta:
        model = CredentialAccessRequest
        fields = (
            "id", "credential_id", "credential_label", "credential_type",
            "requester_id", "requester_email", "requester_name", "reason",
            "requested_hours", "status", "decided_by_email", "decided_at",
            "decision_note", "granted_until", "can_view_password", "created_at",
        )
        read_only_fields = fields

    def get_requester_name(self, obj) -> str:
        u = obj.requester
        return f"{u.first_name} {u.last_name}".strip() or u.email

    def get_decided_by_email(self, obj) -> str | None:
        return obj.decided_by.email if obj.decided_by_id else None


class SubTeamCredentialGrantSerializer(BaseModelSerializer):
    """Read shape for a group grant."""

    sub_team_name = serializers.CharField(source="sub_team.name", read_only=True)
    credential_label = serializers.SerializerMethodField()
    granted_by_email = serializers.SerializerMethodField()

    class Meta:
        model = SubTeamCredentialGrant
        fields = (
            "id", "sub_team", "sub_team_name", "scope", "credential_type",
            "credential", "credential_label", "folder", "folder_name",
            "can_view_password", "granted_by_email", "created_at",
        )
        read_only_fields = fields

    folder_name = serializers.SerializerMethodField()

    def get_credential_label(self, obj) -> str | None:
        return obj.credential.label if obj.credential_id else None

    def get_folder_name(self, obj) -> str | None:
        return obj.folder.name if obj.folder_id else None

    def get_granted_by_email(self, obj) -> str | None:
        return obj.granted_by.email if obj.granted_by_id else None


class SubTeamCredentialGrantWriteSerializer(serializers.Serializer):
    """Write shape. Mirrors the model's clean(), because DRF never calls it.

    `can_view_password` defaults to False: a grant is use-only until the owner
    deliberately widens it. That is the opposite of CredentialShareWrite's
    default, and deliberately so, since a grant can cover the whole vault.
    """

    scope = serializers.ChoiceField(choices=SubTeamCredentialGrant.Scope.choices)
    credential_type = serializers.ChoiceField(
        choices=Credential.CredentialType.choices, required=False, allow_blank=True,
    )
    credential = serializers.UUIDField(required=False, allow_null=True)
    folder = serializers.UUIDField(required=False, allow_null=True)
    can_view_password = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        scope = attrs["scope"]
        cred_type = attrs.get("credential_type") or ""
        credential = attrs.get("credential")
        folder = attrs.get("folder")
        if scope == SubTeamCredentialGrant.Scope.FOLDER:
            if not folder:
                raise serializers.ValidationError({"folder": "Required for a folder grant."})
            if cred_type or credential:
                raise serializers.ValidationError("A folder grant takes no other target.")
            return attrs
        if folder:
            raise serializers.ValidationError({"folder": "Only a folder grant takes a folder."})
        if scope == SubTeamCredentialGrant.Scope.ALL:
            if cred_type or credential:
                raise serializers.ValidationError(
                    "A grant covering all credentials takes no target."
                )
        elif scope == SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE:
            if not cred_type:
                raise serializers.ValidationError(
                    {"credential_type": "Required for a credential-type grant."}
                )
            if credential:
                raise serializers.ValidationError(
                    {"credential": "Not allowed on a credential-type grant."}
                )
        else:
            if not credential:
                raise serializers.ValidationError(
                    {"credential": "Required for a single-credential grant."}
                )
            if cred_type:
                raise serializers.ValidationError(
                    {"credential_type": "Not allowed on a single-credential grant."}
                )
        return attrs


class PasswordHistorySerializer(BaseModelSerializer):
    """One retired password — metadata only; the value comes from /reveal/."""

    changed_by_email = serializers.SerializerMethodField()
    replaced_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = CredentialPasswordHistory
        fields = ("id", "set_at", "replaced_at", "changed_by_email")
        read_only_fields = fields

    def get_changed_by_email(self, obj) -> str | None:
        return obj.changed_by.email if obj.changed_by_id else None


class CredentialActivitySerializer(BaseModelSerializer):
    """One access-log row for a single credential's activity list."""

    user_email = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = CredentialAccessLog
        fields = ("id", "user_email", "user_name", "action", "ip_address", "created_at")
        read_only_fields = fields

    def get_user_email(self, obj) -> str | None:
        return obj.user.email if obj.user_id else None

    def get_user_name(self, obj) -> str:
        if not obj.user_id:
            return "Scheduled task"
        u = obj.user
        return f"{u.first_name} {u.last_name}".strip() or u.email


class VaultFolderSerializer(BaseModelSerializer):
    """A folder, with how many of its credentials the caller can see and — for
    the owner, who manages access — which groups it is shared with."""

    credential_count = serializers.IntegerField(read_only=True, default=0)
    groups = serializers.SerializerMethodField()
    # People the folder is shared with directly. Managers and owners only.
    members = serializers.SerializerMethodField()

    class Meta:
        model = VaultFolder
        fields = ("id", "name", "credential_count", "groups", "members", "created_at")
        read_only_fields = ("id", "credential_count", "groups", "members", "created_at")

    def get_members(self, obj) -> list[dict] | None:
        if not self.context.get("include_members"):
            return None
        return [
            {
                "user_id": str(fs.user_id),
                "name": f"{fs.user.first_name} {fs.user.last_name}".strip() or fs.user.email,
                "email": fs.user.email,
                "can_view_password": fs.can_view_password,
            }
            for fs in obj.shares.all()
        ]

    def get_groups(self, obj) -> list[dict] | None:
        if not self.context.get("include_groups"):
            return None
        return [
            {
                "grant_id": str(g.pk),
                "sub_team": str(g.sub_team_id),
                "sub_team_name": g.sub_team.name,
                "can_view_password": g.can_view_password,
            }
            for g in obj.grants.all()
        ]

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("A folder needs a name.")
        return value


class FolderShareWriteSerializer(serializers.Serializer):
    user_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    # Off unless asked for, like every share.
    can_view_password = serializers.BooleanField(default=False)
