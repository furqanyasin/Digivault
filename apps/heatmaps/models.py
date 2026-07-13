from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class HeatmapEvent(BaseModel):
    """Lightweight interaction events for portal heatmap overlays."""

    class EventType(models.TextChoices):
        CLICK = "click", "Click"
        SCROLL = "scroll", "Scroll"
        MOUSEMOVE = "mousemove", "Mouse move"

    team = models.ForeignKey(
        "accounts.Team",
        on_delete=models.CASCADE,
        related_name="heatmap_events",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="heatmap_events",
    )
    page_path = models.CharField(max_length=500, db_index=True)
    page_title = models.CharField(max_length=200, blank=True)
    event_type = models.CharField(
        max_length=20,
        choices=EventType.choices,
        db_index=True,
    )
    x = models.FloatField(default=0.0)
    y = models.FloatField(default=0.0)
    viewport_width = models.PositiveIntegerField(default=0)
    viewport_height = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.event_type} on {self.page_path}"
