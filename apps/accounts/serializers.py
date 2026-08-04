from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.accounts.models import PasswordResetRequest, Team, TeamInvitation, TeamMembership, User
from apps.common.serializers import BaseModelSerializer


class UserRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField(
        validators=[UniqueValidator(queryset=User.objects.all())]
    )
    password = serializers.CharField(write_only=True, min_length=8)
    name = serializers.CharField(max_length=150)

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        name = validated_data.pop("name", "")
        parts = name.split(" ", 1)
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=parts[0],
            last_name=parts[1] if len(parts) > 1 else "",
        )
        return user


class UserSerializer(BaseModelSerializer):
    active_team = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "timezone", "active_team", "must_change_password", "created_at")
        read_only_fields = ("id", "email", "active_team", "must_change_password", "created_at")


class TeamSerializer(BaseModelSerializer):
    member_count = serializers.SerializerMethodField()
    my_role = serializers.SerializerMethodField()
    my_features = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ("id", "name", "slug", "plan", "member_count", "my_role", "my_features", "created_at")
        read_only_fields = ("id", "slug", "created_at")

    def get_member_count(self, obj) -> int:
        return obj.memberships.count()

    def _my_membership(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None
        return obj.memberships.filter(user=request.user).first()

    def get_my_role(self, obj) -> str | None:
        """The requesting user's role in this team — lets the UI gate
        manager-only sections without an extra members fetch."""
        m = self._my_membership(obj)
        return m.role if m else None

    def get_my_features(self, obj) -> list:
        """Effective feature keys for the requesting user — drives nav/page
        gating in the frontend layout. Owner gets everything; other roles get
        their stored feature_access (falling back to the role default)."""
        from apps.accounts.features import effective_features

        m = self._my_membership(obj)
        return effective_features(m.role, m.feature_access) if m else []


class TeamMembershipSerializer(BaseModelSerializer):
    user = UserSerializer(read_only=True)
    totp_enabled = serializers.BooleanField(source="user.totp_enabled", read_only=True)
    # Effective access (stored override or role default) so the UI chips reflect
    # what the member actually sees, even for legacy rows with no stored value.
    effective_features = serializers.SerializerMethodField()

    class Meta:
        model = TeamMembership
        fields = ("id", "user", "role", "feature_access", "effective_features", "totp_enabled", "created_at")
        read_only_fields = ("id", "totp_enabled", "created_at")

    def get_effective_features(self, obj) -> list:
        from apps.accounts.features import effective_features

        return effective_features(obj.role, obj.feature_access)


class TeamInvitationSerializer(BaseModelSerializer):
    invited_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = TeamInvitation
        fields = ("id", "email", "role", "invited_by", "token", "accepted", "created_at")
        read_only_fields = ("id", "invited_by", "token", "accepted", "created_at")


class TeamSettingsSerializer(serializers.ModelSerializer):
    clickup_api_token = serializers.CharField(allow_blank=True, required=False)
    clickup_connected = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ("id", "name", "clickup_api_token", "clickup_connected", "clickup_list_id")
        read_only_fields = ("id",)

    def get_clickup_connected(self, obj) -> bool:
        return bool(obj.clickup_api_token)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Mask the token — show only last 6 chars
        token = data.get("clickup_api_token") or ""
        data["clickup_api_token_masked"] = ("••••••" + token[-6:]) if len(token) > 6 else ("•" * len(token))
        data["clickup_api_token"] = ""  # never expose the full token
        return data


class PasswordResetRequestSerializer(BaseModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name = serializers.SerializerMethodField()
    approved_by_email = serializers.EmailField(source="approved_by.email", read_only=True, default=None)

    class Meta:
        model = PasswordResetRequest
        fields = ("id", "user_email", "user_name", "status", "approved_by_email", "approved_at", "created_at")
        read_only_fields = fields

    def get_user_name(self, obj) -> str:
        name = f"{obj.user.first_name} {obj.user.last_name}".strip()
        return name or obj.user.email
