from django.db import models

from apps.common.models import BaseModel


class Report(BaseModel):
    """A generated client report for one website over a period.

    The rendered file (PDF or CSV) is stored on `file`; `status` tracks
    generation. Created on-demand via the API or by the monthly Celery task.
    """

    class Format(models.TextChoices):
        PDF = "pdf", "PDF"
        CSV = "csv", "CSV"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    team = models.ForeignKey(
        "accounts.Team", on_delete=models.CASCADE, related_name="reports"
    )
    website = models.ForeignKey(
        "websites.Website", on_delete=models.CASCADE, related_name="reports"
    )
    period_start = models.DateField()
    period_end = models.DateField()
    report_format = models.CharField(
        max_length=4, choices=Format.choices, default=Format.PDF
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    file = models.FileField(upload_to="reports/", null=True, blank=True)
    error = models.TextField(blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["team", "-created_at"])]

    def __str__(self) -> str:
        return f"Report({self.website} {self.period_start}–{self.period_end} {self.report_format})"
