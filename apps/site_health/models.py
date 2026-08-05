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

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

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

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["website", "-occurred_at"])]

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
