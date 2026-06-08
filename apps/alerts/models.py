from django.db import models

from apps.common.models import BaseModel


class AlertRule(BaseModel):
    """Team-level configuration controlling when and how alerts are delivered.

    Rules can be global (website=None, applies to all sites) or per-website.
    Per-website rules take precedence over global rules for that site.
    """

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        SLACK = "slack", "Slack"
        IN_APP = "in_app", "In-App"

    class DeliveryMode(models.TextChoices):
        IMMEDIATE = "immediate", "Immediate"
        HOURLY_DIGEST = "hourly_digest", "Hourly Digest"
        DAILY_DIGEST = "daily_digest", "Daily Digest"

    team = models.ForeignKey(
        "accounts.Team",
        on_delete=models.CASCADE,
        related_name="alert_rules",
    )
    # None = global rule for all websites on this team
    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="alert_rules",
    )
    channel = models.CharField(max_length=10, choices=Channel.choices)
    # Minimum severity level that triggers this rule
    min_severity = models.CharField(
        max_length=10,
        choices=[("high", "High only"), ("medium", "Medium & above"), ("low", "All")],
        default="medium",
    )
    # JSON array of change_type strings; empty list = all types
    change_types = models.JSONField(default=list)
    delivery_mode = models.CharField(
        max_length=20, choices=DeliveryMode.choices, default=DeliveryMode.IMMEDIATE
    )
    # Channel-specific destination
    slack_webhook_url = models.URLField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["team", "channel"]

    def __str__(self) -> str:
        target = self.website.domain if self.website else "all sites"
        return f"{self.team.name} — {self.channel} ({target})"


class AlertSuppression(BaseModel):
    """Mute alerts for a known script on a website (by provider or source domain).

    Checked in AlertService.dispatch_for_change — a change whose script matches
    an active suppression produces no notifications.
    """

    class MatchType(models.TextChoices):
        PROVIDER = "provider", "Provider"
        DOMAIN = "domain", "Source domain"

    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="alert_suppressions",
    )
    match_type = models.CharField(max_length=10, choices=MatchType.choices)
    match_value = models.CharField(max_length=255)
    reason = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alert_suppressions",
    )

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("website", "match_type", "match_value")]

    def __str__(self) -> str:
        return f"suppress {self.match_type}={self.match_value} on {self.website}"

    def matches(self, change) -> bool:
        script = getattr(change, "script", None)
        if script is None:
            return False
        if self.match_type == self.MatchType.PROVIDER:
            return (script.provider or "") == self.match_value
        return (script.src_domain or "") == self.match_value


class Notification(BaseModel):
    """A generated alert instance for one rule + one script change."""

    class DeliveryStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    team = models.ForeignKey(
        "accounts.Team",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    # Nullable — domain alerts don't have a script change
    script_change = models.ForeignKey(
        "scripts.ScriptChange",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    rule = models.ForeignKey(
        AlertRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    channel = models.CharField(max_length=10, choices=AlertRule.Channel.choices)
    delivery_status = models.CharField(
        max_length=10,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
    )
    delivered_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    # Digest grouping — set to the digest period start when mode != immediate
    digest_period_start = models.DateTimeField(null=True, blank=True)

    read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "read", "-created_at"]),
            models.Index(fields=["team", "delivery_status"]),
        ]

    def __str__(self) -> str:
        return f"Notification({self.channel}, {self.delivery_status}) {self.website}"
