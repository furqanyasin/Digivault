from django.db import models

from apps.common.models import BaseModel
from apps.common.querysets import ActiveQuerySet, TeamScopedQuerySet


class ScriptQuerySet(TeamScopedQuerySet, ActiveQuerySet):
    """Combined queryset for Script — supports both .for_team() and .active()."""

    def for_team(self, team):
        return self.filter(website__team=team)

    def unknown(self):
        return self.filter(provider="unknown")

    def by_category(self, category: str):
        return self.filter(category=category)


class Script(BaseModel):
    """A unique third-party script detected on a website.

    One record per (website, src_url) pair. Updated in place when snippet
    data arrives for an existing URL; a new record is created for new URLs.
    """

    class Location(models.TextChoices):
        HEAD = "head", "Head"
        BODY = "body", "Body"
        FOOTER = "footer", "Footer"
        DYNAMIC = "dynamic", "Dynamic (injected after load)"
        UNKNOWN = "unknown", "Unknown"

    class Scope(models.TextChoices):
        GLOBAL = "global", "Global (all pages)"
        PAGE_SPECIFIC = "page_specific", "Page-specific"
        ONE_TIME = "one_time", "One-time / test"

    class Category(models.TextChoices):
        ANALYTICS = "analytics", "Analytics"
        ADVERTISING = "advertising", "Advertising"
        TAG_MANAGEMENT = "tag_management", "Tag Management"
        SESSION_RECORDING = "session_recording", "Session Recording"
        CALL_TRACKING = "call_tracking", "Call & Conversion Tracking"
        CHAT = "chat", "Chat & Support"
        CRM = "crm", "CRM & Marketing Automation"
        PAYMENT = "payment", "Payment"
        SEO = "seo", "SEO & Verification"
        SECURITY = "security", "Security & CAPTCHA"
        PERFORMANCE = "performance", "Performance & CDN"
        SOCIAL = "social", "Social & Reviews"
        UNKNOWN = "unknown", "Unknown"

    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="scripts",
    )
    src_url = models.TextField()
    src_domain = models.CharField(max_length=255, blank=True, db_index=True)
    provider = models.CharField(max_length=100, default="unknown", db_index=True)
    category = models.CharField(
        max_length=30, choices=Category.choices, default=Category.UNKNOWN, db_index=True
    )
    location = models.CharField(
        max_length=20, choices=Location.choices, default=Location.UNKNOWN
    )
    scope = models.CharField(
        max_length=20, choices=Scope.choices, default=Scope.GLOBAL
    )
    is_async = models.BooleanField(default=False)
    is_defer = models.BooleanField(default=False)
    is_inline = models.BooleanField(default=False)
    # SHA-256 of inline script content for change detection
    inline_hash = models.CharField(max_length=64, blank=True)

    # WordPress-specific enrichment
    wp_plugin = models.CharField(max_length=200, blank=True)
    wp_post_id = models.IntegerField(null=True, blank=True)

    # URL patterns where this script has been seen
    seen_on_pages = models.JSONField(default=list)

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "Pending Review"
        APPROVED = "approved", "Approved"
        BLOCKED = "blocked", "Blocked"
        IGNORED = "ignored", "Ignored"

    is_active = models.BooleanField(default=True, db_index=True)
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PENDING, db_index=True
    )
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    objects = ScriptQuerySet.as_manager()

    class Meta:
        ordering = ["provider", "src_domain"]
        unique_together = [("website", "src_url")]
        indexes = [
            models.Index(fields=["website", "is_active", "category"]),
            models.Index(fields=["website", "provider"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider} — {self.src_domain} ({self.website})"


class ScriptSnapshot(BaseModel):
    """Raw payload from one snippet page-load event.

    Retained for 90 days then purged by a scheduled Celery task.
    Used as the source of truth for the diff engine.
    """

    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    page_url = models.TextField()
    # Full list of detected scripts as [{src, location, async, defer, inline, ...}]
    scripts_data = models.JSONField()
    user_agent = models.TextField(blank=True)
    snippet_version = models.CharField(max_length=20, blank=True)
    captured_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-captured_at"]
        indexes = [
            models.Index(fields=["website", "page_url", "-captured_at"]),
        ]

    def __str__(self) -> str:
        return f"Snapshot {self.website} @ {self.page_url} ({self.captured_at})"


class ScriptChange(BaseModel):
    """A detected change event produced by the diff engine."""

    class ChangeType(models.TextChoices):
        ADDED = "added", "Script Added"
        REMOVED = "removed", "Script Removed"
        MOVED = "moved", "Script Moved"
        URL_CHANGED = "url_changed", "Script URL Changed"
        PLUGIN_CHANGED = "plugin_changed", "Plugin Source Changed"
        INLINE_CHANGED = "inline_changed", "Inline Content Changed"

    class Severity(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="changes",
    )
    script = models.ForeignKey(
        Script,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="changes",
    )
    change_type = models.CharField(max_length=20, choices=ChangeType.choices)
    severity = models.CharField(
        max_length=10, choices=Severity.choices, default=Severity.MEDIUM
    )
    description = models.CharField(max_length=500)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)

    # Acknowledgement
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_changes",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["website", "-created_at"]),
            models.Index(fields=["website", "severity", "acknowledged_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.severity} {self.change_type} on {self.website}"

    @property
    def is_acknowledged(self) -> bool:
        return self.acknowledged_at is not None


class DetectedForm(BaseModel):
    """A web form detected on a website page by the tracking snippet.

    Unique per (website, page_url, form_action).  Updated in place on each
    ingest so that field lists stay current without duplication.
    """

    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="detected_forms",
    )
    page_url = models.TextField()
    form_id = models.CharField(max_length=200, blank=True)
    form_name = models.CharField(max_length=200, blank=True)
    form_action = models.TextField(blank=True)
    form_method = models.CharField(max_length=10, default="post")
    # JSON list: [{name, type, label, required}]
    fields = models.JSONField(default=list)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page_url", "form_action"]
        unique_together = [("website", "page_url", "form_action")]
        indexes = [
            models.Index(fields=["website", "page_url"]),
        ]

    def __str__(self) -> str:
        return f"Form {self.form_action or '(no action)'} on {self.page_url}"
