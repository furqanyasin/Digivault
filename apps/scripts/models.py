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

    # Heuristic injected-code flags, set on ingest from apps.scripts.suspicion.
    # Advisory only: Digivault sees the URL, not the script body, so these mark
    # things worth a human look rather than proven malware. Reasons are stored so
    # the flag is never shown without its justification.
    is_suspicious = models.BooleanField(default=False, db_index=True)
    suspicion_severity = models.CharField(max_length=10, blank=True)
    suspicion_reasons = models.JSONField(default=list, blank=True)
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

    class RecipientSource(models.TextChoices):
        PAGE = "page", "Read from the page markup"
        WORDPRESS = "wordpress", "Reported by WordPress"

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
    # Where this form's submissions are configured to go:
    # {"to": [...], "cc": [...], "bcc": [...]}. Read from form *configuration*
    # only — a mailto: action, recipient data- attributes, hidden input values,
    # or the site's own form plugin over WP Connect — never from what a visitor
    # types. Empty lists when the destination is configured server-side and no
    # WP Connect snippet has reported it.
    #
    # A dict rather than a single address because real forms have several: an
    # Elementor "To" holding "sales@x.com, dev@x.com" used to store nothing at
    # all, because a comma-joined value is not one valid address.
    recipients = models.JSONField(default=dict, blank=True)
    # Deprecated, superseded by `recipients` above. Still written by the current
    # writers until they move over, and dropped once a release has run on the
    # new field. Read through `primary_recipient(form.recipients)`, never here.
    recipient_email = models.CharField(max_length=254, blank=True, default="")
    # How the recipient above was learned. The page markup is a proxy for the
    # form's configuration; WordPress is the configuration itself, so it wins
    # and an ingest must not overwrite it (see _upsert_form). Also lets the UI
    # state which of the two it is rather than implying equal confidence.
    recipient_source = models.CharField(
        max_length=10,
        choices=RecipientSource.choices,
        blank=True,
        default="",
    )
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

        Derived from detection type, identifiers and action, plus the set of
        field names **only when the form has neither an id nor a name**, so that
        re-sends of the same form update in place while distinct forms on one
        page (including action-less div forms) stay separate.

        The field set is deliberately excluded once an identifier exists,
        because it is not stable across observations of one form. The snippet
        posts several times per page load and again at submit time, and a
        multi-step form mounts only the step it is showing — so the fields seen
        at DOMContentLoaded are not the fields seen at submit. Hashing them
        listed `multiStepForm` twice on the same path: the page-load steps
        stuck at 0 submits, and a second row created by the submit report
        (which stores a form whose fingerprint matches nothing) holding every
        conversion. An id or a name is what genuinely identifies a form within
        a page; which of its fields happen to be mounted is not.

        Volatile fields — nonces, honeypots, captcha tokens, hex-named
        anti-spam fields — rotate per page load and are excluded, otherwise
        an anonymous form would mint a "new" row on every visit and counts
        inflate.

        The action is normalized for the same reason. `form.action` in the
        browser resolves to the *document* URL when the attribute is absent, so
        an action-less form (Elementor, and most page-builder forms) reports a
        different action for every campaign, ad and referral URL the page is
        reached by. Hashing that raw minted one row per URL variant: the same
        form listed several times in the Forms tab with its submissions split
        across the copies. Two forms that genuinely post to different query
        strings on one path now share an identity — a deliberate trade, since
        their ids and field sets still tell them apart.
        """
        import hashlib
        import re

        from apps.scripts.normalize import normalize_page_url

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
        form_id = form_data.get("form_id", "") or ""
        form_name = form_data.get("form_name", "") or ""
        basis = "|".join([
            form_data.get("detection_type", DetectedForm.DetectionType.NATIVE),
            form_id,
            form_name,
            # Relative actions ("/submit") have no netloc and pass through
            # unchanged — they are already free of the document URL.
            normalize_page_url(form_data.get("form_action", "") or ""),
            # Emptied rather than dropped for an identified form, so the segment
            # count stays fixed and an id can never hash the same as an
            # anonymous form whose field name sits in that position.
            "" if (form_id or form_name) else ",".join(field_names),
        ])
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]

    def __str__(self) -> str:
        return f"Form {self.form_action or '(no action)'} on {self.page_url}"


class JsError(BaseModel):
    """A JavaScript error caught on a client page by the tracking snippet.

    Deduplicated per (website, fingerprint) with a hit counter rather than one
    row per occurrence: a broken script on a busy page throws thousands of
    identical errors, and storing each would bury the signal and the disk.

    page_url and message are sanitised before save, and no user input, cookie or
    storage value is ever captured — only the browser's own error metadata.
    """

    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="js_errors",
    )
    # Stable hash of message + source + line, so repeats collapse onto one row.
    fingerprint = models.CharField(max_length=64, db_index=True)
    message = models.TextField()
    # The file that threw, plus position — what a developer needs to find it.
    source_url = models.TextField(blank=True)
    line_no = models.PositiveIntegerField(null=True, blank=True)
    col_no = models.PositiveIntegerField(null=True, blank=True)
    # First frames only; a full trace can be enormous and adds little here.
    stack = models.TextField(blank=True)
    page_url = models.TextField()
    # Coarse browser label, not a full user-agent string — enough to spot a
    # browser-specific break without storing a fingerprintable identifier.
    browser = models.CharField(max_length=60, blank=True)
    hits = models.PositiveIntegerField(default=1)
    last_seen_at = models.DateTimeField(auto_now=True)
    is_resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-last_seen_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["website", "fingerprint"], name="jserror_unique_per_site"
            ),
        ]
        indexes = [
            models.Index(fields=["website", "-last_seen_at"]),
            models.Index(fields=["website", "is_resolved"]),
        ]

    def __str__(self) -> str:
        return f"JsError({self.website}: {self.message[:60]})"


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
    # When this row's failure was announced to the team. Only the row that
    # actually raised the alert is stamped — that is what the per-form cooldown
    # in apps.scripts.notifications reads, so a form that keeps failing gets
    # re-reported once a day instead of once ever.
    alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["website", "-created_at"]),
            models.Index(fields=["website", "form_id", "-alerted_at"]),
        ]

    def __str__(self) -> str:
        return f"Form error on {self.page_url}: {self.message[:60]}"
