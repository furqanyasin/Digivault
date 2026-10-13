import uuid

from django.db import models
from django.utils import timezone

from apps.accounts.models import Team


class MonitorQuerySet(models.QuerySet):
    def for_team(self, team):
        return self.filter(team=team)

    def active(self):
        return self.filter(is_active=True)


class Monitor(models.Model):
    class MonitorType(models.TextChoices):
        HTTP = "http", "HTTP/HTTPS"
        PING = "ping", "Ping"
        PORT = "port", "Port"
        SSL = "ssl", "SSL Certificate"

    class Status(models.TextChoices):
        UP = "up", "Up"
        DOWN = "down", "Down"
        DEGRADED = "degraded", "Degraded"
        # A named WAF answered instead of the site. We learned nothing about the
        # origin, so this is neither up nor down — reporting it as down is what
        # made healthy sites page their owners.
        BLOCKED = "blocked", "Blocked"
        PAUSED = "paused", "Paused"
        PENDING = "pending", "Pending"

    class CheckInterval(models.IntegerChoices):
        SECONDS_30 = 30, "Every 30 seconds"
        MINUTE_1 = 60, "Every 1 minute"
        MINUTES_2 = 120, "Every 2 minutes"
        MINUTES_5 = 300, "Every 5 minutes"
        MINUTES_10 = 600, "Every 10 minutes"
        MINUTES_15 = 900, "Every 15 minutes"
        MINUTES_30 = 1800, "Every 30 minutes"
        HOUR_1 = 3600, "Every hour"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="monitors")
    # Links a monitor to the website it watches (set for auto-provisioned
    # monitors). Lets uptime alerts route to the website's notification channel
    # and powers the status-page card on the website detail page.
    website = models.ForeignKey(
        "websites.Website", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="monitors",
    )

    name = models.CharField(max_length=200)
    url = models.CharField(max_length=2000)
    monitor_type = models.CharField(
        max_length=20, choices=MonitorType.choices, default=MonitorType.HTTP
    )

    # HTTP options
    expected_status_code = models.PositiveIntegerField(default=200)
    request_method = models.CharField(max_length=10, default="GET")
    request_headers = models.JSONField(default=dict, blank=True)
    request_body = models.TextField(blank=True)
    keyword = models.CharField(
        max_length=500,
        blank=True,
        help_text="If set, response body must contain this string",
    )

    # Port options
    port = models.PositiveIntegerField(null=True, blank=True)

    # Scheduling
    # 15 minutes, not seconds: every check leaves from the platform's single
    # public IP, and frequent polling across the whole client fleet is what gets
    # that IP challenged or blocked by Cloudflare/Sucuri/AWS WAF.
    check_interval = models.PositiveIntegerField(
        default=CheckInterval.MINUTES_15,
        choices=CheckInterval.choices,
    )
    timeout = models.PositiveIntegerField(default=30, help_text="Seconds")
    retry_count = models.PositiveIntegerField(
        default=3, help_text="Consecutive failures before incident"
    )

    # Current state
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    is_active = models.BooleanField(default=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    # Blocks are suppressed rather than alerted, so they need their own counter:
    # without it a permanently blocked monitor would go permanently silent.
    consecutive_blocks = models.PositiveIntegerField(default=0)
    is_alerting = models.BooleanField(default=False)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_response_time = models.PositiveIntegerField(
        null=True, blank=True, help_text="ms"
    )

    # Cached uptime stats
    uptime_24h = models.FloatField(null=True, blank=True)
    uptime_7d = models.FloatField(null=True, blank=True)
    uptime_30d = models.FloatField(null=True, blank=True)

    tags = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MonitorQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.url})"

    def recalculate_uptime(self):
        """Recompute and cache uptime percentages from check history.

        Blocked checks are excluded from both sides of the ratio. A WAF answered
        instead of the origin, so we never observed that period at all — scoring
        it as downtime invents an outage, and scoring it as uptime invents
        health. A window of nothing but blocks reports None, which is the
        truthful answer: we do not know.
        """
        now = timezone.now()
        windows = {
            "uptime_24h": now - timezone.timedelta(hours=24),
            "uptime_7d": now - timezone.timedelta(days=7),
            "uptime_30d": now - timezone.timedelta(days=30),
        }
        for field, since in windows.items():
            observable = MonitorCheck.objects.filter(
                monitor=self, checked_at__gte=since
            ).exclude(status=MonitorCheck.Status.BLOCKED)
            total = observable.count()
            if total == 0:
                setattr(self, field, None)
            else:
                up = observable.filter(status=MonitorCheck.Status.UP).count()
                setattr(self, field, round((up / total) * 100, 2))
        Monitor.objects.filter(pk=self.pk).update(
            uptime_24h=self.uptime_24h,
            uptime_7d=self.uptime_7d,
            uptime_30d=self.uptime_30d,
        )


class MonitorCheck(models.Model):
    class Status(models.TextChoices):
        UP = "up", "Up"
        DOWN = "down", "Down"
        DEGRADED = "degraded", "Degraded"
        BLOCKED = "blocked", "Blocked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    monitor = models.ForeignKey(
        Monitor, on_delete=models.CASCADE, related_name="checks"
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    response_time_ms = models.PositiveIntegerField(null=True, blank=True)
    status_code = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    # "" = our own request; "google" = Google's PageSpeed run, used when a
    # firewall blocks our IP (monitors.second_opinion).
    checked_via = models.CharField(max_length=10, blank=True, default="")
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["monitor", "checked_at"]),
        ]

    def __str__(self):
        return f"{self.monitor.name} — {self.status} at {self.checked_at}"


class MonitorUptimeRollup(models.Model):
    """Daily aggregate of MonitorCheck rows for one monitor.

    Raw checks are purged after a retention window (see monitors.purge_old_checks);
    these rollups are the durable long-term record used for trends and reporting.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    monitor = models.ForeignKey(
        Monitor, on_delete=models.CASCADE, related_name="uptime_rollups"
    )
    date = models.DateField()
    checks_total = models.PositiveIntegerField(default=0)
    checks_up = models.PositiveIntegerField(default=0)
    checks_degraded = models.PositiveIntegerField(default=0)
    avg_response_time_ms = models.FloatField(null=True, blank=True)
    uptime_pct = models.FloatField(default=0.0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        unique_together = ("monitor", "date")
        indexes = [
            models.Index(fields=["monitor", "date"]),
        ]

    def __str__(self):
        return f"{self.monitor.name} {self.date}: {self.uptime_pct}%"


class NotificationChannel(models.Model):
    """Reusable outbound notification destination scoped to a team.

    config stores channel-specific fields:
      slack/discord/webhook → {"url": "https://..."}
      email               → {"addresses": ["a@b.com"]}
      telegram            → {"bot_token": "...", "chat_id": "..."}
    """

    class ChannelType(models.TextChoices):
        EMAIL = "email", "Email"
        CLICKUP = "clickup", "ClickUp"
        SLACK = "slack", "Slack"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="notification_channels")
    name = models.CharField(max_length=200)
    channel_type = models.CharField(max_length=20, choices=ChannelType.choices)
    config = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.channel_type})"


class MonitorNotificationRule(models.Model):
    """Links a monitor to a notification channel with event trigger settings."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    monitor = models.ForeignKey(Monitor, on_delete=models.CASCADE, related_name="notification_rules")
    channel = models.ForeignKey(NotificationChannel, on_delete=models.CASCADE, related_name="monitor_rules")
    notify_on_down = models.BooleanField(default=True)
    notify_on_recovery = models.BooleanField(default=True)
    notify_on_degraded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("monitor", "channel")
        ordering = ["monitor", "channel"]

    def __str__(self):
        return f"{self.monitor.name} → {self.channel.name}"
