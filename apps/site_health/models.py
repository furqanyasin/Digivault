from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel


class PhpError(BaseModel):
    class Level(models.TextChoices):
        FATAL = "fatal", "Fatal"
        ERROR = "error", "Error"
        WARNING = "warning", "Warning"
        NOTICE = "notice", "Notice"
        DEPRECATED = "deprecated", "Deprecated"
        INFO = "info", "Info"

    website = models.ForeignKey(
        "websites.Website", on_delete=models.CASCADE, related_name="php_errors"
    )
    level = models.CharField(max_length=20, choices=Level.choices, default=Level.ERROR, db_index=True)
    message = models.TextField()
    file = models.CharField(max_length=500, blank=True)
    line = models.IntegerField(null=True, blank=True)
    url = models.CharField(max_length=2048, blank=True)
    raw = models.TextField(blank=True)
    captured_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-captured_at"]
        indexes = [models.Index(fields=["website", "-captured_at"])]

    def __str__(self):
        return f"[{self.level.upper()}] {self.message[:80]}"


class SiteEvent(BaseModel):
    class EventType(models.TextChoices):
        PLUGIN_UPDATED = "plugin_updated", "Plugin Updated"
        PLUGIN_INSTALLED = "plugin_installed", "Plugin Installed"
        PLUGIN_REMOVED = "plugin_removed", "Plugin Removed"
        THEME_CHANGED = "theme_changed", "Theme Changed"
        CORE_UPDATED = "core_updated", "Core Updated"
        DEPLOYMENT = "deployment", "Deployment"
        MANUAL = "manual", "Manual Entry"
        # Passive discovery: a page URL the snippet had never reported before.
        # There is no matching "page updated" — the snippet sees a page's scripts,
        # not its content, so an edit is invisible without a WordPress-side hook.
        PAGE_DISCOVERED = "page_discovered", "Page Discovered"
        SEO_NOINDEX_DETECTED = "seo_noindex_detected", "SEO: noindex detected"
        SEO_ROBOTS_BLOCK = "seo_robots_block", "SEO: robots.txt blocks all"
        SEO_SITEMAP_MISSING = "seo_sitemap_missing", "SEO: sitemap missing"
        SEO_META_CHANGED = "seo_meta_changed", "SEO: on-page meta changed"
        # Where a form delivers changed. Not a "script" change — it comes from
        # the form's own configuration (a mailto: action, or the site's form
        # plugin read over WP Connect), so it has no ScriptChange to hang off
        # and lives here, on the site's timeline.
        FORM_RECIPIENTS_CHANGED = "form_recipients_changed", "Form recipients changed"
        # --- WP Connect (snippet v2). Unlike everything above, these are
        # attributed: a WordPress hook fired, so we know who and from where.
        WP_LOGIN = "wp_login", "WP: user logged in"
        WP_LOGIN_FAILED = "wp_login_failed", "WP: login failed"
        WP_USER_CREATED = "wp_user_created", "WP: user created"
        WP_USER_UPDATED = "wp_user_updated", "WP: user updated"
        WP_USER_ROLE_CHANGED = "wp_user_role_changed", "WP: role changed"
        WP_USER_DELETED = "wp_user_deleted", "WP: user deleted"
        WP_PASSWORD_RESET = "wp_password_reset", "WP: password reset"
        WP_PLUGIN_ACTIVATED = "wp_plugin_activated", "WP: plugin activated"
        WP_PLUGIN_DEACTIVATED = "wp_plugin_deactivated", "WP: plugin deactivated"
        WP_PLUGIN_UPDATED = "wp_plugin_updated", "WP: plugin updated"
        WP_PLUGIN_DELETED = "wp_plugin_deleted", "WP: plugin deleted"
        WP_THEME_SWITCHED = "wp_theme_switched", "WP: theme switched"
        WP_THEME_UPDATED = "wp_theme_updated", "WP: theme updated"
        WP_THEME_DELETED = "wp_theme_deleted", "WP: theme deleted"
        WP_CORE_UPDATED = "wp_core_updated", "WP: core updated"
        WP_POST_PUBLISHED = "wp_post_published", "WP: post published"
        WP_POST_UPDATED = "wp_post_updated", "WP: post updated"
        WP_POST_TRASHED = "wp_post_trashed", "WP: post trashed"
        WP_POST_DELETED = "wp_post_deleted", "WP: post deleted"
        WP_ORDER_STATUS_CHANGED = "wp_order_status_changed", "WC: order status changed"
        WP_PRODUCT_UPDATED = "wp_product_updated", "WC: product updated"
        WP_ORDER_REFUNDED = "wp_order_refunded", "WC: order refunded"
        WP_BUFFER_OVERFLOW = "wp_buffer_overflow", "WP: event buffer overflowed"
        # From the file-integrity walk, not a hook: a checksum changed between
        # two complete walks of wp-content.
        WP_FILE_CHANGED = "wp_file_changed", "WP: file changed on disk"

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    class Source(models.TextChoices):
        PASSIVE = "passive", "Passive detection"
        WP_CONNECT = "wp_connect", "WP Connect"
        MANUAL = "manual", "Manual entry"

    class Category(models.TextChoices):
        USERS = "users", "Users"
        PLUGINS = "plugins", "Plugins"
        THEMES = "themes", "Themes"
        CORE = "core", "WordPress core"
        CONTENT = "content", "Posts & pages"
        COMMERCE = "commerce", "WooCommerce"
        FILES = "files", "Files"
        SEO = "seo", "SEO"
        FORMS = "forms", "Forms"
        DISCOVERY = "discovery", "Discovery"

    website = models.ForeignKey(
        "websites.Website", on_delete=models.CASCADE, related_name="site_events"
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    summary = models.CharField(max_length=500)
    details = models.JSONField(default=dict, blank=True)
    actor = models.CharField(max_length=200, blank=True)
    severity = models.CharField(
        max_length=20, choices=Severity.choices, default=Severity.INFO, db_index=True
    )
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    source = models.CharField(
        max_length=20, choices=Source.choices, default=Source.PASSIVE, db_index=True
    )
    # Stored rather than derived from event_type: the enum is ~45 values and the
    # Change Log filters on category, which needs an index to stay cheap.
    category = models.CharField(max_length=20, choices=Category.choices, blank=True)
    actor_ip = models.GenericIPAddressField(null=True, blank=True)
    # The WordPress user ID as well as the login, because logins get renamed and
    # the ID is what still links two events to the same person afterwards.
    actor_wp_id = models.IntegerField(null=True, blank=True)
    object_type = models.CharField(max_length=30, blank=True)
    object_id = models.CharField(max_length=200, blank=True)
    # The snippet buffer's autoincrement id. A gap means a flush was lost.
    sequence = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["website", "-occurred_at"]),
            models.Index(fields=["website", "category", "-occurred_at"]),
        ]

    def __str__(self):
        return f"{self.event_type}: {self.summary}"


class VulnerabilityReport(BaseModel):
    class Severity(models.TextChoices):
        CRITICAL = "critical", "Critical"
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    class ComponentType(models.TextChoices):
        PLUGIN = "plugin", "Plugin"
        THEME = "theme", "Theme"
        CORE = "core", "WordPress Core"

    website = models.ForeignKey(
        "websites.Website", on_delete=models.CASCADE, related_name="vulnerabilities"
    )
    component_type = models.CharField(max_length=20, choices=ComponentType.choices)
    component_name = models.CharField(max_length=200, db_index=True)
    component_version = models.CharField(max_length=50, blank=True)
    cve_ids = models.JSONField(default=list)
    severity = models.CharField(max_length=20, choices=Severity.choices, db_index=True)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    fixed_in_version = models.CharField(max_length=50, blank=True)
    source = models.CharField(max_length=50, default="wpscan")
    references = models.JSONField(default=list)

    class Meta:
        ordering = ["severity", "component_name"]
        unique_together = [("website", "component_name", "title")]

    def __str__(self):
        return f"{self.severity.upper()} — {self.title}"


class SiteScanState(BaseModel):
    """One-per-website record tracking scan status and detected components."""

    website = models.OneToOneField(
        "websites.Website", on_delete=models.CASCADE, related_name="scan_state"
    )
    last_scanned_at = models.DateTimeField(null=True, blank=True)
    scan_status = models.CharField(max_length=20, default="never")
    wp_version = models.CharField(max_length=20, blank=True)
    wp_latest_version = models.CharField(max_length=20, blank=True)
    wp_update_available = models.BooleanField(default=False)
    plugins_detected = models.JSONField(default=list)
    error = models.TextField(blank=True)

    def __str__(self):
        return f"ScanState({self.website})"


class SeoReport(BaseModel):
    """One-per-website snapshot of robots/sitemap/indexability health."""

    website = models.OneToOneField(
        "websites.Website", on_delete=models.CASCADE, related_name="seo_report"
    )
    last_checked_at = models.DateTimeField(null=True, blank=True)
    check_status = models.CharField(max_length=20, default="never")  # never/running/done/failed
    error = models.TextField(blank=True)

    robots_status = models.CharField(max_length=20, default="unknown")  # found/missing/error
    robots_blocks_all = models.BooleanField(default=False)
    robots_content = models.TextField(blank=True)  # raw robots.txt (truncated)

    sitemap_status = models.CharField(max_length=20, default="unknown")  # found/missing/error
    sitemap_url = models.CharField(max_length=2048, blank=True)
    sitemap_url_count = models.PositiveIntegerField(default=0)
    sitemap_pages = models.JSONField(default=list)  # the sitemap's URLs (capped) for display

    homepage_indexable = models.BooleanField(null=True, blank=True)
    # Cumulative across scans: [{"url","indexable","reason","checked_at"}]. Each
    # run checks a rotating window of pages and merges the results in, so the
    # full set fills out over a few daily runs without one heavy scan.
    pages_checked = models.JSONField(default=list)
    noindex_count = models.PositiveIntegerField(default=0)
    scan_cursor = models.PositiveIntegerField(default=0)  # rotation offset into the page list

    # On-page SEO signals captured from the homepage each run. Changes between
    # runs raise SEO_META_CHANGED SiteEvents (see run_seo_check).
    meta_title = models.CharField(max_length=500, blank=True)
    meta_description = models.TextField(blank=True)
    h1 = models.CharField(max_length=500, blank=True)
    canonical_url = models.CharField(max_length=2048, blank=True)
    schema_types = models.JSONField(default=list)  # detected schema.org @type values

    def __str__(self):
        return f"SeoReport({self.website})"


class SecurityHeaderReport(BaseModel):
    """One-per-website snapshot of HTTP security-header posture (CSP, HSTS,
    X-Frame-Options, …) graded into a 0–100 score and a letter grade."""

    website = models.OneToOneField(
        "websites.Website", on_delete=models.CASCADE, related_name="security_header_report"
    )
    last_checked_at = models.DateTimeField(null=True, blank=True)
    check_status = models.CharField(max_length=20, default="never")  # never/running/done/failed
    error = models.TextField(blank=True)

    final_url = models.CharField(max_length=2048, blank=True)
    status_code = models.PositiveIntegerField(null=True, blank=True)

    score = models.PositiveSmallIntegerField(default=0)
    grade = models.CharField(max_length=2, default="")  # A+, A, B, C, D, F
    # [{name, key, present, status, value, recommendation, weight}]
    headers = models.JSONField(default=list)
    pass_count = models.PositiveSmallIntegerField(default=0)
    warn_count = models.PositiveSmallIntegerField(default=0)
    fail_count = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return f"SecurityHeaderReport({self.website}: {self.grade})"


class FileManifest(BaseModel):
    """One WordPress file walk: path -> md5 across wp-content.

    Stored from Phase 0, diffed from Phase 3. The snippet keeps no baseline of
    its own — Stacks Monitor holds it and diffs. MalCare markets "we don't bloat your
    database", and keeping a 50k-row checksum table on the client would be doing
    the thing they market against; the diff also belongs in Python, where it can
    be tested as a pure function beside DiffEngine.

    `is_complete` exists because the walk arrives in slices. Diffing a partial
    manifest would report every not-yet-walked file as removed — the same
    failure mode that made snapshot-to-snapshot script diffing unusable.
    """

    website = models.ForeignKey(
        "websites.Website", on_delete=models.CASCADE, related_name="file_manifests"
    )
    walk_id = models.CharField(max_length=64)
    entries = models.JSONField(default=dict, blank=True)
    is_complete = models.BooleanField(default=False)
    walked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("website", "walk_id")]
        indexes = [models.Index(fields=["website", "-created_at"])]

    def __str__(self):
        return f"FileManifest({self.website}, {len(self.entries)} files)"
