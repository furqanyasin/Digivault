import uuid

from django.db import models
from django.utils import timezone

from apps.accounts.models import Team
from apps.monitors.models import Monitor, MonitorCheck


class StatusPageQuerySet(models.QuerySet):
    def for_team(self, team):
        return self.filter(team=team)


class StatusPage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="status_pages")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    allow_indexing = models.BooleanField(
        default=False,
        help_text="Allow search engines to index this page. Off by default.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = StatusPageQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def overall_status(self) -> str:
        """Return 'operational', 'degraded', or 'outage' based on active monitors."""
        statuses = list(
            self.monitors.filter(
                monitor__is_active=True
            ).values_list("monitor__status", flat=True)
        )
        if not statuses:
            return "operational"
        if "down" in statuses:
            return "outage"
        if "degraded" in statuses:
            return "degraded"
        return "operational"


class StatusPageMonitor(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status_page = models.ForeignKey(
        StatusPage, on_delete=models.CASCADE, related_name="monitors"
    )
    monitor = models.ForeignKey(
        Monitor, on_delete=models.CASCADE, related_name="status_page_entries"
    )
    display_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional override name shown on the public page.",
    )
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "display_name"]
        unique_together = ("status_page", "monitor")

    def __str__(self):
        return f"{self.status_page.name} → {self.monitor.name}"

    def uptime_bars(self, days: int = 90) -> list[dict]:
        """Return daily uptime status for the last `days` days (oldest first)."""
        now = timezone.now()
        result = []
        for i in range(days - 1, -1, -1):
            day_start = (now - timezone.timedelta(days=i)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_end = day_start + timezone.timedelta(days=1)
            checks = MonitorCheck.objects.filter(
                monitor=self.monitor,
                checked_at__gte=day_start,
                checked_at__lt=day_end,
            )
            total = checks.count()
            if total == 0:
                status = "no-data"
            else:
                down = checks.filter(status=MonitorCheck.Status.DOWN).count()
                degraded = checks.filter(status=MonitorCheck.Status.DEGRADED).count()
                if down > 0:
                    status = "down"
                elif degraded > 0:
                    status = "degraded"
                else:
                    status = "up"
            result.append({"date": day_start.date().isoformat(), "status": status})
        return result
