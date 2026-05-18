import uuid

from django.db import models


class PerformanceReport(models.Model):
    """One Lighthouse/PageSpeed Insights run for a website URL."""

    class Strategy(models.TextChoices):
        MOBILE = "mobile", "Mobile"
        DESKTOP = "desktop", "Desktop"

    class Rating(models.TextChoices):
        FAST = "fast", "Fast"
        AVERAGE = "average", "Average"
        SLOW = "slow", "Slow"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="performance_reports",
    )
    url = models.URLField(max_length=2000)
    strategy = models.CharField(max_length=10, choices=Strategy.choices, default=Strategy.MOBILE)

    # Overall Lighthouse score 0-100
    performance_score = models.PositiveSmallIntegerField(null=True, blank=True)

    # Core Web Vitals
    fcp_ms = models.PositiveIntegerField(null=True, blank=True, help_text="First Contentful Paint ms")
    lcp_ms = models.PositiveIntegerField(null=True, blank=True, help_text="Largest Contentful Paint ms")
    cls_score = models.FloatField(null=True, blank=True, help_text="Cumulative Layout Shift")
    tbt_ms = models.PositiveIntegerField(null=True, blank=True, help_text="Total Blocking Time ms")
    ttfb_ms = models.PositiveIntegerField(null=True, blank=True, help_text="Time to First Byte ms")
    si_ms = models.PositiveIntegerField(null=True, blank=True, help_text="Speed Index ms")
    tti_ms = models.PositiveIntegerField(null=True, blank=True, help_text="Time to Interactive ms")
    inp_ms = models.PositiveIntegerField(null=True, blank=True, help_text="Interaction to Next Paint ms")

    # Ratings per metric
    fcp_rating = models.CharField(max_length=10, choices=Rating.choices, blank=True)
    lcp_rating = models.CharField(max_length=10, choices=Rating.choices, blank=True)
    cls_rating = models.CharField(max_length=10, choices=Rating.choices, blank=True)
    tbt_rating = models.CharField(max_length=10, choices=Rating.choices, blank=True)

    error = models.TextField(blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["website", "strategy", "-checked_at"]),
        ]

    def __str__(self):
        return f"{self.website} — score={self.performance_score} ({self.strategy})"


class CruxReport(models.Model):
    """Chrome UX Report — real-user field data at the 75th percentile (p75).

    Fetched weekly from the free CrUX API (no key required).
    https://developer.chrome.com/docs/crux/api/
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="crux_reports",
    )
    origin = models.URLField(max_length=500)

    # p75 values
    lcp_p75_ms = models.PositiveIntegerField(null=True, blank=True, help_text="LCP p75 ms")
    fcp_p75_ms = models.PositiveIntegerField(null=True, blank=True, help_text="FCP p75 ms")
    cls_p75 = models.FloatField(null=True, blank=True, help_text="CLS p75")
    inp_p75_ms = models.PositiveIntegerField(null=True, blank=True, help_text="INP p75 ms")
    ttfb_p75_ms = models.PositiveIntegerField(null=True, blank=True, help_text="TTFB p75 ms")
    fid_p75_ms = models.PositiveIntegerField(null=True, blank=True, help_text="FID p75 ms (legacy)")

    # Distribution percentages (good / needs-improvement / poor) for Core Web Vitals
    lcp_good = models.FloatField(null=True, blank=True)
    lcp_ni = models.FloatField(null=True, blank=True)
    lcp_poor = models.FloatField(null=True, blank=True)

    fcp_good = models.FloatField(null=True, blank=True)
    fcp_ni = models.FloatField(null=True, blank=True)
    fcp_poor = models.FloatField(null=True, blank=True)

    cls_good = models.FloatField(null=True, blank=True)
    cls_ni = models.FloatField(null=True, blank=True)
    cls_poor = models.FloatField(null=True, blank=True)

    inp_good = models.FloatField(null=True, blank=True)
    inp_ni = models.FloatField(null=True, blank=True)
    inp_poor = models.FloatField(null=True, blank=True)

    error = models.TextField(blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fetched_at"]
        indexes = [
            models.Index(fields=["website", "-fetched_at"]),
        ]

    def __str__(self):
        return f"{self.website} — CrUX @ {self.fetched_at:%Y-%m-%d}"
