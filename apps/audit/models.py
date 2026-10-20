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
        AUTH_SIGNUP = "auth.signup", "Signed up"
        PLATFORM_PLAN_CHANGED = "platform.plan_changed", "Plan changed by platform owner"
        PLATFORM_USER_UPDATED = "platform.user_updated", "User updated by platform owner"
        # Credentials
        CREDENTIAL_CREATED = "credential.created", "Credential created"
        CREDENTIAL_REVEALED = "credential.revealed", "Credential revealed"
        CREDENTIAL_UPDATED = "credential.updated", "Credential updated"
        CREDENTIAL_DELETED = "credential.deleted", "Credential deleted"
        CREDENTIAL_SHARED = "credential.shared", "Credential shared"
        CREDENTIAL_UNSHARED = "credential.unshared", "Credential unshared"
        CREDENTIAL_IMPORTED = "credential.imported", "Credentials imported"
        CREDENTIAL_EXPORTED = "credential.exported", "Credentials exported"
        CREDENTIAL_GROUP_GRANTED = "credential.group_granted", "Credential granted to a group"
        CREDENTIAL_GROUP_REVOKED = "credential.group_revoked", "Group credential grant revoked"
        CREDENTIAL_ACCESS_REQUESTED = "credential.access_requested", "Credential access requested"
        CREDENTIAL_ACCESS_APPROVED = "credential.access_approved", "Credential access approved"
        CREDENTIAL_ACCESS_DENIED = "credential.access_denied", "Credential access denied"
        CREDENTIAL_HANDOVER = "credential.handover", "Credentials handed over"
        CREDENTIAL_TOTP_READ = "credential.totp_read", "Authenticator code read"
        CREDENTIAL_REPORTED_BROKEN = "credential.reported_broken", "Credential reported broken"
        CREDENTIAL_MARKED_FIXED = "credential.marked_fixed", "Credential marked fixed"
        # Websites
        WEBSITE_CREATED = "website.created", "Website created"
        WEBSITE_DELETED = "website.deleted", "Website deleted"
        WEBSITE_SCAN_TRIGGERED = "website.scan_triggered", "Scan triggered"
        WEBSITE_SNIPPET_VERIFIED = "website.snippet_verified", "Snippet verified"
        WEBSITE_CHANGE_ACKNOWLEDGED = "website.change_acknowledged", "Change acknowledged"
        SCRIPT_REVIEWED = "script.reviewed", "Script reviewed"
        # Monitors
        MONITOR_CREATED = "monitor.created", "Monitor created"
        MONITOR_PAUSED = "monitor.paused", "Monitor paused"
        MONITOR_RESUMED = "monitor.resumed", "Monitor resumed"
        # Reports
        REPORT_GENERATED = "report.generated", "Report generated"
        REPORT_DELETED = "report.deleted", "Report deleted"
        # Status pages
        STATUS_PAGE_CREATED = "status_page.created", "Status page created"
        STATUS_PAGE_DELETED = "status_page.deleted", "Status page deleted"
        # Team
        TEAM_MEMBER_INVITED = "team.member_invited", "Member invited"
        TEAM_MEMBER_JOINED = "team.member_joined", "Member joined"
        TEAM_MEMBER_ROLE_CHANGED = "team.member_role_changed", "Member role changed"
        TEAM_MEMBER_REMOVED = "team.member_removed", "Member removed"
        TEAM_CREATED = "team.created", "Team/department created"
        TEAM_GROUP_CREATED = "team.group_created", "Group created"
        TEAM_GROUP_UPDATED = "team.group_updated", "Group updated"
        TEAM_GROUP_DELETED = "team.group_deleted", "Group deleted"
        TEAM_MEMBER_GROUP_CHANGED = "team.member_group_changed", "Member group changed"
        # Settings
        SETTINGS_TEAM_NAME_CHANGED = "settings.team_name_changed", "Team name changed"
        SETTINGS_INTEGRATION_UPDATED = "settings.integration_updated", "Integration updated"
        # Clients
        CLIENT_CREATED = "client.created", "Client created"
        CLIENT_UPDATED = "client.updated", "Client updated"
        CLIENT_STATUS_CHANGED = "client.status_changed", "Client status changed"
        CLIENT_SYNCED = "client.synced", "Client synced from ClickUp"
        CLIENT_IMPORTED = "client.imported", "Clients imported"
        CLIENT_EXPORTED = "client.exported", "Clients exported"
        CLIENT_DELETED = "client.deleted", "Client deleted"
        # Alerts
        ALERT_RULE_CREATED = "alert.rule_created", "Alert rule created"
        ALERT_RULE_UPDATED = "alert.rule_updated", "Alert rule updated"
        ALERT_RULE_DELETED = "alert.rule_deleted", "Alert rule deleted"
        NOTIFICATION_CHANNEL_CREATED = "alert.channel_created", "Notification channel created"
        NOTIFICATION_CHANNEL_DELETED = "alert.channel_deleted", "Notification channel deleted"
        NOTIFICATION_CHANNEL_APPLIED_ALL = (
            "alert.channel_applied_all", "Notification channel applied to all websites"
        )
        # Monitors (extended)
        MONITOR_UPDATED = "monitor.updated", "Monitor updated"
        MONITOR_DELETED = "monitor.deleted", "Monitor deleted"
        MONITOR_RULE_CREATED = "monitor.rule_created", "Monitor rule created"
        MONITOR_RULE_DELETED = "monitor.rule_deleted", "Monitor rule deleted"
        # Status page incidents / maintenance
        INCIDENT_POSTED = "status_page.incident_posted", "Incident posted"
        INCIDENT_UPDATED = "status_page.incident_updated", "Incident updated"
        INCIDENT_DELETED = "status_page.incident_deleted", "Incident deleted"
        MAINTENANCE_SCHEDULED = "status_page.maintenance_scheduled", "Maintenance scheduled"
        MAINTENANCE_DELETED = "status_page.maintenance_deleted", "Maintenance deleted"
        # Websites (extended)
        WEBSITE_UPDATED = "website.updated", "Website updated"
        WEBSITE_SNIPPET_REGENERATED = "website.snippet_regenerated", "Snippet regenerated"
        WEBSITE_WP_LOGIN = "website.wp_login", "WP admin login link issued"
        WEBSITE_WP_SSO_SECRET_ROTATED = "website.wp_sso_secret_rotated", "WP SSO secret rotated"
        WEBSITE_WP_SNIPPET_VIEWED = "website.wp_snippet_viewed", "WP Connect snippet viewed"
        # Domains / performance
        DOMAIN_REFRESHED = "domain.refreshed", "Domain info refreshed"
        PERFORMANCE_CHECK_RUN = "performance.check_run", "Performance check run"
        CRUX_FETCHED = "performance.crux_fetched", "CrUX data fetched"

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
