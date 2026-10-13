from django.db import models

from apps.common.models import BaseModel
from apps.common.querysets import TeamScopedQuerySet


class HeatmapQuerySet(TeamScopedQuerySet):
    def for_team(self, team):
        return self.filter(website__team=team)


class HeatmapActivity(BaseModel):
    """One aggregated interaction cell on a page, normalized to percentages.

    The snippet normalizes every raw interaction (click, mouse move, scroll
    endpoint) to a position on the page *as a fraction of it*, not of any one
    screen: x is the percentage of the viewport width, y is the percentage of
    the full page height (document position, so scrolling is already included).
    It then bins those positions into a 100x100 percentage grid and sums them
    client-side before POSTing.

    Storing percentage cells instead of raw pixel events is what keeps this
    table small on a busy site (a click storm is a handful of cell rows, not
    tens of thousands of events) while still letting the dashboard render a
    heatmap overlay that lines up on any viewport.

    Aggregation happens in the snippet; the ingest task only sums into these
    rows (count += N), so the pipeline never touches per-event granularity.
    """

    class Kind(models.TextChoices):
        CLICK = "click", "Click"
        MOVE = "move", "Move"
        SCROLL = "scroll", "Scroll"
        RAGE = "rage", "Rage click"

    class Device(models.TextChoices):
        DESKTOP = "desktop", "Desktop"
        MOBILE = "mobile", "Mobile / Tablet"

    class VisitorType(models.TextChoices):
        NEW = "new", "New"
        RETURNING = "returning", "Returning"

    class Source(models.TextChoices):
        DIRECT = "direct", "Direct"
        ORGANIC = "organic", "Organic"
        SOCIAL = "social", "Social"
        EMAIL = "email", "Email"
        REFERRAL = "referral", "Referral"

    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="heatmap_activity",
    )
    page_url = models.TextField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # Percentage position: x (0-100 of viewport width) and y (0-100 of page
    # height). Integers from the snippet's 100x100 grid binning.
    x = models.PositiveSmallIntegerField()
    y = models.PositiveSmallIntegerField()
    device = models.CharField(
        max_length=10, choices=Device.choices, default=Device.DESKTOP
    )
    # Segmentation dimensions reported by the snippet alongside device. Cells
    # are aggregated per segment so the dashboard can filter and compare
    # cohorts; "all" is expressed client-side as "no filter" (drop the param).
    visitor_type = models.CharField(
        max_length=10, choices=VisitorType.choices, default=VisitorType.NEW
    )
    source = models.CharField(
        max_length=10, choices=Source.choices, default=Source.DIRECT
    )
    # Summed events landing in this cell (clicks / sampled moves / scroll visits).
    count = models.PositiveIntegerField(default=0)
    # Best-effort descriptor of the element that occupies this cell (e.g.
    # `button#add-to-cart` or link text). Attribute-only: it is keyed to the
    # aggregated cell, not part of its identity, and reflects the most recent
    # observation. Blank for move/scroll and for body-level clicks.
    element = models.CharField(max_length=300, blank=True, default="")
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    objects = HeatmapQuerySet.as_manager()

    class Meta:
        ordering = ["-count"]
        constraints = [
            models.UniqueConstraint(
                fields=["website", "page_url", "kind", "device", "visitor_type", "source", "x", "y"],
                name="heatmap_activity_cell_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["website", "page_url", "kind", "device", "visitor_type", "source"]),
            models.Index(fields=["website", "page_url", "-last_seen_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.x}%,{self.y}% x{self.count} ({self.website})"


class HeatmapPageStats(BaseModel):
    """Aggregate snapshot of one page's interaction for a site.

    One row per (website, page_url, device). Feed the page selector, the
    summary header (visits, clicks, scroll depth) and the scroll map. A row is
    upserted (not appended) each time the snippet posts, so visits is a running
    count of observations.
    """

    class Device(models.TextChoices):
        DESKTOP = "desktop", "Desktop"
        MOBILE = "mobile", "Mobile / Tablet"

    class VisitorType(models.TextChoices):
        NEW = "new", "New"
        RETURNING = "returning", "Returning"

    class Source(models.TextChoices):
        DIRECT = "direct", "Direct"
        ORGANIC = "organic", "Organic"
        SOCIAL = "social", "Social"
        EMAIL = "email", "Email"
        REFERRAL = "referral", "Referral"

    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="heatmap_pages",
    )
    page_url = models.TextField()
    device = models.CharField(
        max_length=10, choices=Device.choices, default=Device.DESKTOP
    )
    # Segmentation dimensions (mirror HeatmapActivity) so per-segment rows can
    # carry their own visits/click totals and scroll histogram.
    visitor_type = models.CharField(
        max_length=10, choices=VisitorType.choices, default=VisitorType.NEW
    )
    source = models.CharField(
        max_length=10, choices=Source.choices, default=Source.DIRECT
    )
    # Number of aggregated observations (pageviews) contributed so far.
    visits = models.PositiveIntegerField(default=0)
    total_clicks = models.PositiveIntegerField(default=0)
    # Maximum scroll depth reached as a percentage of page height.
    max_scroll_percent = models.PositiveSmallIntegerField(default=0)
    # Scroll depth histogram keyed by percent bucket -> share of visits that
    # reached at least that far, as a float 0..1. Built by the ingest task so
    # the dashboard's scroll map only reads one row.
    scroll_histogram = models.JSONField(default=dict, blank=True)
    # Raw material for the histogram above: {bucket: number_of_visits_that_
    # reached_it}. A share cannot be accumulated by overwriting it with each
    # visit's own reach — that just reports the most recent visitor — so the
    # counts are kept and `scroll_histogram` is re-derived as count / visits on
    # every final flush. Internal to the ingest task; not serialized.
    scroll_bucket_counts = models.JSONField(default=dict, blank=True)
    # Page geometry as last observed, in CSS pixels. The dashboard renders the
    # overlay at page_height / viewport_width, so it can size the canvas at the
    # page's true aspect instead of asking an operator to guess it.
    page_height = models.PositiveIntegerField(default=0)
    viewport_width = models.PositiveIntegerField(default=0)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    objects = HeatmapQuerySet.as_manager()

    class Meta:
        ordering = ["-visits"]
        constraints = [
            models.UniqueConstraint(
                fields=["website", "page_url", "device", "visitor_type", "source"],
                name="heatmap_page_stats_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["website", "page_url"]),
            models.Index(fields=["website", "-last_seen_at"]),
        ]

    def __str__(self) -> str:
        return f"Heatmap stats {self.page_url} ({self.device}) — {self.visits} visits"


def snapshot_upload_path(instance, filename: str) -> str:
    return f"heatmap/snapshots/{instance.website_id}/{instance.pk or 'new'}.png"


class HeatmapPageSnapshot(BaseModel):
    """A rendered picture of one page, used as the heatmap's backdrop.

    The dashboard originally drew the overlay on a live ``<iframe>`` of the
    client's homepage. That fails three ways at once: it ignores which page was
    selected, most origins refuse to be framed at all (``X-Frame-Options`` /
    CSP ``frame-ancestors``) leaving a blank box, and a live page has no fixed
    height so the overlay had to be aligned by dragging a slider.

    Capturing the page once, at a known width and height, fixes all three — it
    is what Hotjar does. The iframe remains as the fallback for pages that have
    no snapshot yet, so the dashboard degrades rather than going blank.

    One row per (website, page_url, device): a snapshot is a picture of a page,
    so it is deliberately *not* keyed by segment — every visitor_type/source
    cohort of the same page shares one backdrop.

    Images are served through a team-scoped view, never from ``MEDIA_URL``.
    These are pictures of clients' pages and can show pre-login marketing
    copy, pricing or staging content; a guessable public URL would leak them.
    """

    class Device(models.TextChoices):
        DESKTOP = "desktop", "Desktop"
        MOBILE = "mobile", "Mobile / Tablet"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        # The origin's WAF answered instead of the page. Mirrors the monitor's
        # `blocked` status: we learned nothing, so it is not a capture failure
        # to retry aggressively.
        BLOCKED = "blocked", "Blocked"
        # Chromium is not installed in this deployment. Distinct from `failed`
        # so the dashboard can say "screenshots are off" rather than "capture
        # broke", and so a retry sweep can skip these rows entirely.
        UNAVAILABLE = "unavailable", "Capture unavailable"

    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="heatmap_snapshots",
    )
    page_url = models.TextField()
    device = models.CharField(
        max_length=10, choices=Device.choices, default=Device.DESKTOP
    )
    image = models.ImageField(upload_to=snapshot_upload_path, blank=True, null=True)
    # Dimensions of the captured image in CSS pixels. The overlay maps its
    # percentage cells straight onto these, so they must be stored with the
    # image rather than re-measured from it (a device-pixel-ratio > 1 capture
    # would otherwise double the reported size).
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    error_message = models.TextField(blank=True, default="")
    captured_at = models.DateTimeField(null=True, blank=True)

    objects = HeatmapQuerySet.as_manager()

    class Meta:
        ordering = ["-captured_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["website", "page_url", "device"],
                name="heatmap_page_snapshot_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["website", "page_url", "device"]),
            models.Index(fields=["status", "captured_at"]),
        ]

    def __str__(self) -> str:
        return f"Snapshot {self.page_url} ({self.device}) — {self.status}"
