import secrets

from django.db import models

from apps.common.models import BaseModel
from apps.common.querysets import TeamScopedQuerySet


class Website(BaseModel):
    """A client website registered with Digivault.

    Each website gets a unique site_id used to authenticate the JS snippet.
    The snippet itself is a computed property — no extra storage needed.
    """

    class Platform(models.TextChoices):
        WORDPRESS = "wordpress", "WordPress"
        WEBFLOW = "webflow", "Webflow"
        WIX = "wix", "Wix"
        FRAMER = "framer", "Framer"
        SHOPIFY = "shopify", "Shopify"
        SQUARESPACE = "squarespace", "Squarespace"
        CUSTOM = "custom", "Custom"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    team = models.ForeignKey(
        "accounts.Team",
        on_delete=models.CASCADE,
        related_name="websites",
    )
    client = models.ForeignKey(
        "clients.Client",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="websites",
    )
    name = models.CharField(max_length=200)
    domain = models.CharField(max_length=255)
    platform = models.CharField(
        max_length=20, choices=Platform.choices, default=Platform.OTHER
    )
    # 43-char URL-safe token — embedded in public HTML, acts as an identifier
    # not a secret; rate-limiting protects against replay abuse
    site_id = models.CharField(max_length=64, unique=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    notes = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    health_score = models.IntegerField(default=100)
    # Flagship / high-value sites, surfaced in their own dashboard section.
    # Per-site rather than per-client: a client often has one site that matters
    # and several that don't.
    is_vip = models.BooleanField(
        default=False,
        help_text="Surface this site in the dashboard's VIP section.",
    )

    SEO_INTERVAL_CHOICES = [
        (0, "Off"),
        (1, "Daily"),
        (3, "Every 3 days"),
        (7, "Every 7 days"),
        (14, "Every 14 days"),
        (30, "Every 30 days"),
    ]
    seo_scan_interval_days = models.PositiveSmallIntegerField(
        choices=SEO_INTERVAL_CHOICES, default=0,
        help_text="How often to auto-run the SEO health check. 0 = off.",
    )
    # One channel for all of this site's alerts (uptime, domain/SSL/hosting,
    # SEO). When unset, alerts fall back to the team's active channels.
    notification_channel = models.ForeignKey(
        "monitors.NotificationChannel",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    # Downtime/uptime alerts get their own channel so they can route separately
    # from general website alerts. When unset, uptime falls back to
    # notification_channel (then team defaults).
    uptime_notification_channel = models.ForeignKey(
        "monitors.NotificationChannel",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    # Shared secret for one-click wp-admin login via the Digivault Connect
    # WordPress plugin. Empty = SSO not set up for this site. Rotating it
    # invalidates all previously issued links.
    wp_sso_secret = models.CharField(max_length=64, blank=True, default="")

    objects = TeamScopedQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["team", "status"]),
            models.Index(fields=["team", "is_vip"]),
            models.Index(fields=["domain"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.domain})"

    def save(self, *args, **kwargs):
        if not self.site_id:
            self.site_id = self._generate_site_id()
        super().save(*args, **kwargs)

    def regenerate_site_id(self) -> str:
        """Invalidate the existing snippet by issuing a new site_id."""
        self.site_id = self._generate_site_id()
        self.save(update_fields=["site_id"])
        return self.site_id

    # Score thresholds that map health_score onto Status. Kept as constants so
    # the API, the frontend rubric, and the tests all quote one source.
    HEALTH_CRITICAL_BELOW = 60
    HEALTH_WARNING_BELOW = 85

    def recalculate_health_score(self) -> None:
        """Compute and persist a 0-100 health score, and refresh status with it.

        This is the single writer of both `health_score` and `status`.

        The two answer different questions and both are kept: the score is a
        cumulative "how healthy overall", status is "how urgent is the worst open
        issue". Status is NOT a pure function of the score — a single
        unacknowledged high-severity script change costs only 10 points but is
        precisely what this product exists to catch, so it must still read
        critical. Conversely a low score forces at least the matching status, so
        the badge can never say 'active' next to a score of 42.
        """
        from datetime import timedelta

        from django.core.exceptions import ObjectDoesNotExist
        from django.utils import timezone
        from apps.scripts.models import ScriptChange

        from apps.scripts.tasks import _internal_hosts

        deductions = 0

        # Exclude Digivault's own infra (the tracking snippet): its changes are
        # hidden from the UI and can never be acknowledged, so they must not
        # permanently drag the health score down.
        internal = _internal_hosts()
        open_changes = ScriptChange.objects.filter(
            website=self, acknowledged_at__isnull=True
        ).select_related("script")
        pending_sevs = []
        for c in open_changes:
            blob = f"{c.script.src_url if c.script_id else ''} {c.description or ''}".lower()
            if any(h in blob for h in internal):
                continue
            pending_sevs.append(c.severity)

        sev_count: dict[str, int] = {}
        for s in pending_sevs:
            sev_count[s] = sev_count.get(s, 0) + 1

        deductions += min(sev_count.get("critical", 0) * 15, 30)
        deductions += min(sev_count.get("high", 0) * 10, 30)
        deductions += min(sev_count.get("medium", 0) * 3, 15)
        deductions += min(sev_count.get("low", 0) * 1, 5)

        # Urgency flags, collected alongside the deductions. These drive `status`
        # independently of the score, because severity does not survive being
        # summed: one unacknowledged high-severity change is only -10 points but
        # is the single thing this product exists to surface.
        urgent = bool(sev_count.get("critical") or sev_count.get("high"))
        warn = bool(sev_count.get("medium"))

        try:
            d = self.domain_info
            now = timezone.now()
            if d.expires_at:
                days = max(0, (d.expires_at - now).days)
                if days <= 7:
                    deductions += 20
                    urgent = True
                elif days <= 30:
                    deductions += 8
                    warn = True
            if d.ssl_expires_at:
                days = max(0, (d.ssl_expires_at - now).days)
                if days <= 7:
                    deductions += 20
                    urgent = True
                elif days <= 14:
                    deductions += 12
                    warn = True
                elif days <= 30:
                    deductions += 5
                    warn = True
            # Hosting renewal is manually entered and was previously unscored,
            # even though the Renewal Center tracks it alongside domain and SSL.
            if d.hosting_expires_at:
                days = max(0, (d.hosting_expires_at - now).days)
                if days <= 7:
                    deductions += 20
                    urgent = True
                elif days <= 30:
                    deductions += 8
                    warn = True
        except ObjectDoesNotExist:
            pass

        try:
            from apps.site_health.models import VulnerabilityReport
            vuln_sevs = list(
                VulnerabilityReport.objects.filter(website=self)
                .values_list("severity", flat=True)
            )
            v_count: dict[str, int] = {}
            for v in vuln_sevs:
                v_count[v] = v_count.get(v, 0) + 1
            deductions += min(v_count.get("critical", 0) * 8, 16)
            deductions += min(v_count.get("high", 0) * 4, 8)
        except Exception:
            pass

        # Unreviewed active scripts: approving (or blocking/ignoring) a script
        # is how the score is earned back — review is part of site hygiene.
        from apps.scripts.models import Script

        pending_review = (
            Script.objects.filter(
                website=self, is_active=True, review_status=Script.ReviewStatus.PENDING
            )
            .exclude(src_domain__in=internal)
            .count()
        )
        deductions += min(pending_review * 2, 10)

        # Uptime. Without this a hard-down site scored 100 — monitors were never
        # read by the health score at all.
        from apps.monitors.models import Monitor

        monitor_rows = list(
            Monitor.objects.filter(website=self).values_list("status", "uptime_30d")
        )
        statuses = {row[0] for row in monitor_rows}
        if Monitor.Status.DOWN in statuses:
            deductions += 30
            urgent = True  # a site that is down is the most urgent thing there is
        elif Monitor.Status.DEGRADED in statuses:
            deductions += 12
            warn = True

        uptimes = [row[1] for row in monitor_rows if row[1] is not None]
        if uptimes:
            worst = min(uptimes)
            if worst < 95:
                deductions += 15
            elif worst < 99:
                deductions += 5

        # Broken forms. Bounded to 7 days so a fixed form earns its score back
        # rather than being punished by history forever.
        from apps.scripts.models import FormSubmissionError

        recent_form_errors = FormSubmissionError.objects.filter(
            website=self, created_at__gte=timezone.now() - timedelta(days=7)
        ).count()
        deductions += min(recent_form_errors * 6, 18)
        if recent_form_errors:
            warn = True

        # Reporting gap: the snippet stopped sending, so we are blind rather than
        # healthy. Sites that have never reported are exempt — a newly added site
        # has no traffic yet, which is not a fault.
        if self.last_seen_at:
            stale_days = (timezone.now() - self.last_seen_at).days
            if stale_days > 30:
                deductions += 20
                warn = True
            elif stale_days > 7:
                deductions += 10
                warn = True

        score = max(0, min(100, 100 - deductions))

        # 'inactive' is a lifecycle state a human chose; health never overwrites
        # it — only the score is refreshed.
        if self.status == self.Status.INACTIVE:
            Website.objects.filter(pk=self.pk).update(health_score=score)
            return

        # Status is the worse of the urgency flags and the score band. The score
        # band is what stops a badge reading 'active' beside a score of 42; the
        # flags are what stop a single high-severity change being averaged away.
        if urgent or score < self.HEALTH_CRITICAL_BELOW:
            status = self.Status.CRITICAL
        elif warn or score < self.HEALTH_WARNING_BELOW:
            status = self.Status.WARNING
        else:
            status = self.Status.ACTIVE

        Website.objects.filter(pk=self.pk).update(health_score=score, status=status)

    @staticmethod
    def _generate_site_id() -> str:
        return secrets.token_urlsafe(32)

    @property
    def snippet_html(self) -> str:
        """Return the two-line HTML snippet for this website."""
        from django.conf import settings

        cdn_base = getattr(settings, "SNIPPET_CDN_URL", "https://cdn.digivault.digilatics.co")
        return (
            f'<script async src="{cdn_base}/s.js" '
            f'data-site="{self.site_id}"></script>'
        )

    @property
    def wp_sso_snippet(self) -> str:
        """PHP code snippet enabling one-click wp-admin login, with this site's
        secret baked in. Empty until a secret is generated. Pasted into the
        same WPCode/Code Snippets tool used for the tracking script — no plugin."""
        from apps.websites.wp_sso_snippet import build_wp_sso_snippet

        return build_wp_sso_snippet(self.wp_sso_secret)

    @property
    def snippet_instructions(self) -> dict:
        """Return platform-specific installation instructions."""
        instructions = {
            self.Platform.WORDPRESS: (
                "Install WPCode or Code Snippets plugin, create a new snippet, "
                "paste the code below, set Location to 'Footer', and activate it."
            ),
            self.Platform.WEBFLOW: (
                "Go to Project Settings → Custom Code → Footer Code and paste the snippet."
            ),
            self.Platform.WIX: (
                "Go to Settings → Advanced → Custom Code, click + Add Code, "
                "paste below the body tag, and apply to All Pages."
            ),
            self.Platform.FRAMER: (
                "Go to Site Settings → General → Custom Code (End of </body>) "
                "and paste the snippet."
            ),
            self.Platform.SHOPIFY: (
                "Go to Online Store → Themes → Edit Code → theme.liquid, "
                "paste the snippet before </body>."
            ),
            self.Platform.SQUARESPACE: (
                "Go to Settings → Advanced → Code Injection → Footer and paste."
            ),
        }
        return {
            "platform": self.platform,
            "instruction": instructions.get(
                self.platform,
                "Paste the snippet before the closing </body> tag on every page.",
            ),
            "snippet": self.snippet_html,
        }


class WebsiteAssignment(BaseModel):
    """Assigns a team member to a website.

    Once a non-manager user has at least one assignment in a team, they only
    see their assigned websites — enforced in WebsiteViewSet.get_queryset,
    not just hidden in the UI. Owners/managers always see everything.
    """

    website = models.ForeignKey(
        Website, on_delete=models.CASCADE, related_name="assignments"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="website_assignments"
    )
    assigned_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        unique_together = [("website", "user")]
        ordering = ["website", "user"]

    def __str__(self) -> str:
        return f"{self.user} → {self.website}"
