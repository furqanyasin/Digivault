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
    # Identity URL: src_url minus volatile cache-buster params (?ver=, ?nonce=).
    # Uniqueness and diffing key on this; src_url keeps the latest raw form.
    normalized_url = models.TextField(blank=True, default="", db_index=True)
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
        unique_together = [("website", "normalized_url")]
        indexes = [
            models.Index(fields=["website", "is_active", "category"]),
            models.Index(fields=["website", "provider"]),
        ]

    def save(self, *args, **kwargs):
        if not self.normalized_url and self.src_url:
            from apps.scripts.normalize import normalize_script_url

            self.normalized_url = normalize_script_url(self.src_url)
        super().save(*args, **kwargs)

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
        CRITICAL = "critical", "Critical"
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

    Unique per (website, page_url, fingerprint).  Updated in place on each
    ingest so that field lists stay current without duplication.  A page can
    carry several forms (e.g. div-based forms that all post to an empty action),
    so a structural fingerprint — not the action alone — disambiguates them.
    """

    class DetectionType(models.TextChoices):
        NATIVE = "native", "Native <form>"
        DOM = "dom", "Div-based / JS"
        EMBEDDED = "embedded", "Embedded (iframe)"

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
    detection_type = models.CharField(
        max_length=10,
        choices=DetectionType.choices,
        default=DetectionType.NATIVE,
    )
    # For embedded forms — the third-party provider (e.g. "HubSpot", "Typeform").
    provider = models.CharField(max_length=100, blank=True)
    # Structural hash that uniquely identifies a form within a page.
    fingerprint = models.CharField(max_length=64, db_index=True)
    # Count of submit attempts observed by the snippet (native/same-origin
    # forms only — embedded third-party iframes can't be tracked from the page).
    submission_count = models.PositiveIntegerField(default=0)
    # When a submit was last observed. Distinct from last_seen_at, which bumps
    # on every ingest (i.e. every pageview) whether or not anyone submitted.
    last_submission_at = models.DateTimeField(null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page_url", "form_action"]
        unique_together = [("website", "page_url", "fingerprint")]
        indexes = [
            models.Index(fields=["website", "page_url"]),
        ]

    @staticmethod
    def compute_fingerprint(form_data: dict) -> str:
        """Stable 32-char hash identifying a form within a page.

        Derived from detection type, identifiers, action, and the set of field
        names so that re-sends of the same form update in place while distinct
        forms on one page (including action-less div forms) stay separate.

        Volatile fields — nonces, honeypots, captcha tokens, hex-named
        anti-spam fields — rotate per page load and are excluded, otherwise
        every visit would mint a "new" form and counts inflate.
        """
        import hashlib
        import re

        volatile = re.compile(
            r"(nonce|honeypot|^hp-|^_wpcf7|^g-recaptcha|^h-captcha|^ct_|^ak_)",
            re.IGNORECASE,
        )
        hexname = re.compile(r"^[0-9a-f]{12,}$", re.IGNORECASE)
        field_names = sorted(
            name
            for name in (
                (f.get("name", "") or "") for f in form_data.get("fields", [])
            )
            if not (volatile.search(name) or hexname.match(name))
        )
        basis = "|".join([
            form_data.get("detection_type", DetectedForm.DetectionType.NATIVE),
            form_data.get("form_id", "") or "",
            form_data.get("form_name", "") or "",
            form_data.get("form_action", "") or "",
            ",".join(field_names),
        ])
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]

    def __str__(self) -> str:
        return f"Form {self.form_action or '(no action)'} on {self.page_url}"


class FormSubmissionError(BaseModel):
    """A failed form submission observed by the tracking snippet.

    Only server-side failures pass the importance filter (mail/SMTP/5xx —
    see apps.scripts.form_errors); user-validation noise is never stored.
    page_url and message are sanitised before save — no PII at rest.
    """

    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="form_errors",
    )
    # Inferred form plugin/source, e.g. "Contact Form 7", "WPForms".
    source = models.CharField(max_length=100, blank=True)
    form_id = models.CharField(max_length=200, blank=True)
    page_url = models.TextField()
    message = models.TextField()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["website", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Form error on {self.page_url}: {self.message[:60]}"
