from django.db import models

from apps.common.models import BaseModel


class ActivityLog(BaseModel):
    """Immutable audit record of every significant user action.

    Written via AuditService.log() — never updated or deleted by application
    code.  Purged after 90 days by a scheduled Celery task.
    """

    class Action(models.TextChoices):
        # Auth
        AUTH_LOGIN = "auth.login", "Login"
        AUTH_LOGOUT = "auth.logout", "Logout"
        AUTH_LOGIN_FAILED = "auth.login_failed", "Login failed"
        AUTH_2FA_ENABLED = "auth.2fa_enabled", "2FA enabled"
        AUTH_2FA_DISABLED = "auth.2fa_disabled", "2FA disabled"
        AUTH_2FA_SETUP_STARTED = "auth.2fa_setup_started", "2FA setup started"
        AUTH_BACKUP_CODES_REGEN = "auth.backup_codes_regenerated", "Backup codes regenerated"
        # Credentials
        CREDENTIAL_CREATED = "credential.created", "Credential created"
        CREDENTIAL_REVEALED = "credential.revealed", "Credential revealed"
        CREDENTIAL_UPDATED = "credential.updated", "Credential updated"
        CREDENTIAL_DELETED = "credential.deleted", "Credential deleted"
        CREDENTIAL_SHARED = "credential.shared", "Credential shared"
        CREDENTIAL_UNSHARED = "credential.unshared", "Credential unshared"
        # Websites
        WEBSITE_CREATED = "website.created", "Website created"
        WEBSITE_DELETED = "website.deleted", "Website deleted"
        WEBSITE_SCAN_TRIGGERED = "website.scan_triggered", "Scan triggered"
        WEBSITE_SNIPPET_VERIFIED = "website.snippet_verified", "Snippet verified"
        WEBSITE_CHANGE_ACKNOWLEDGED = "website.change_acknowledged", "Change acknowledged"
        # Team
        TEAM_MEMBER_INVITED = "team.member_invited", "Member invited"
        TEAM_MEMBER_JOINED = "team.member_joined", "Member joined"
        TEAM_MEMBER_ROLE_CHANGED = "team.member_role_changed", "Member role changed"
        TEAM_MEMBER_REMOVED = "team.member_removed", "Member removed"
        # Settings
        SETTINGS_TEAM_NAME_CHANGED = "settings.team_name_changed", "Team name changed"
        SETTINGS_INTEGRATION_UPDATED = "settings.integration_updated", "Integration updated"

    team = models.ForeignKey(
        "accounts.Team",
        on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    action = models.CharField(max_length=60, choices=Action.choices, db_index=True)
    resource_type = models.CharField(max_length=40, blank=True)
    resource_id = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=300)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "-created_at"], name="audit_team_created_idx"),
            models.Index(fields=["actor", "-created_at"], name="audit_actor_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.actor} — {self.action} ({self.created_at:%Y-%m-%d %H:%M})"
