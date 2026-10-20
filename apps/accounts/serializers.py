from rest_framework import serializers

from apps.accounts.models import (
    SubTeam,
    Team,
    TeamInvitation,
    TeamMembership,
    User,
)
from apps.common.serializers import BaseModelSerializer


class UserSerializer(BaseModelSerializer):
    active_team = serializers.PrimaryKeyRelatedField(read_only=True)
    # Platform owner (Django superuser): sees every workspace on /platform.
    is_platform_admin = serializers.BooleanField(source="is_superuser", read_only=True)
    show_2fa_reminder = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "email", "first_name", "last_name", "timezone", "active_team",
            "must_change_password", "totp_enabled", "is_platform_admin",
            "show_2fa_reminder", "created_at",
        )
        read_only_fields = (
            "id", "email", "active_team", "must_change_password", "totp_enabled",
            "is_platform_admin", "show_2fa_reminder", "created_at",
        )

    def get_show_2fa_reminder(self, obj) -> bool:
        """True until 2FA is on, except for 24 hours after "Remind me tomorrow"."""
        from django.utils import timezone
        from datetime import timedelta

        if obj.totp_enabled:
            return False
        dismissed = obj.twofa_reminder_dismissed_at
        return dismissed is None or dismissed < timezone.now() - timedelta(hours=24)


class TeamSerializer(BaseModelSerializer):
    member_count = serializers.SerializerMethodField()
    my_role = serializers.SerializerMethodField()
    my_features = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = (
            "id", "name", "slug", "plan", "require_2fa", "member_count", "my_role",
            "my_features", "created_at",
        )
        # The plan is changed by the platform owner only (/platform or Django
        # admin). It used to be writable here, so any owner could PATCH their
        # own team onto an unlimited plan.
        read_only_fields = ("id", "slug", "plan", "require_2fa", "created_at")

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


class SubTeamSerializer(BaseModelSerializer):
    """A credential-access group. `team` comes from the URL, never the body."""

    member_count = serializers.SerializerMethodField()

    class Meta:
        model = SubTeam
        fields = ("id", "name", "description", "member_count", "created_at")
        read_only_fields = ("id", "member_count", "created_at")

    def get_member_count(self, obj) -> int:
        return obj.memberships.count()


class TeamMembershipSerializer(BaseModelSerializer):
    user = UserSerializer(read_only=True)
    totp_enabled = serializers.BooleanField(source="user.totp_enabled", read_only=True)
    # Effective access (stored override or role default) so the UI chips reflect
    # what the member actually sees, even for legacy rows with no stored value.
    effective_features = serializers.SerializerMethodField()
    # Credential-access group. Read-only here: it is written through the
    # owner-gated branches in TeamMemberDetailView and TeamCreateUserView, so a
    # manager PATCHing a role can never set it as a side effect.
    sub_team = serializers.PrimaryKeyRelatedField(read_only=True)
    sub_team_name = serializers.CharField(
        source="sub_team.name", read_only=True, default=None
    )
    # A team can hold several owners, so `role == "owner"` no longer tells the
    # UI which row it must not offer to demote or remove. This does: it is the
    # one owner `Team.owner` points at.
    is_primary_owner = serializers.SerializerMethodField()

    class Meta:
        model = TeamMembership
        fields = (
            "id", "user", "role", "feature_access", "effective_features",
            "totp_enabled", "sub_team", "sub_team_name", "is_primary_owner",
            "created_at",
        )
        read_only_fields = (
            "id", "totp_enabled", "sub_team", "sub_team_name",
            "is_primary_owner", "created_at",
        )

    def get_is_primary_owner(self, obj) -> bool:
        return obj.user_id == obj.team.owner_id

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
    clickup_chat_connected = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = (
            "id", "name", "clickup_api_token", "clickup_connected",
            "clickup_list_id", "clickup_chat_url", "clickup_chat_connected",
        )
        read_only_fields = ("id",)

    def get_clickup_connected(self, obj) -> bool:
        return bool(obj.clickup_api_token)

    def get_clickup_chat_connected(self, obj) -> bool:
        return bool(obj.clickup_chat_url)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Mask the token — show only last 6 chars
        token = data.get("clickup_api_token") or ""
        data["clickup_api_token_masked"] = ("••••••" + token[-6:]) if len(token) > 6 else ("•" * len(token))
        data["clickup_api_token"] = ""  # never expose the full token
        return data
