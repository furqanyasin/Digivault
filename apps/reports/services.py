"""Report generation — gather data, render, persist the file."""

from __future__ import annotations

from datetime import date

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.reports.builder import ReportBuilder
from apps.reports.models import Report


def generate_report(
    website, period_start: date, period_end: date, report_format: str = Report.Format.PDF
) -> Report:
    """Create a Report, render it, and save the file. Returns the Report."""
    report = Report.objects.create(
        team=website.team,
        website=website,
        period_start=period_start,
        period_end=period_end,
        report_format=report_format,
        status=Report.Status.PENDING,
    )
    try:
        data = ReportBuilder.gather(website, period_start, period_end)
        if report_format == Report.Format.CSV:
            content = ReportBuilder.render_csv(data).encode("utf-8")
            ext = "csv"
        else:
            content = ReportBuilder.render_pdf(data)
            ext = "pdf"

        filename = f"{website.domain}_{period_start}_{period_end}.{ext}".replace("/", "_")
        report.file.save(filename, ContentFile(content), save=False)
        report.status = Report.Status.DONE
        report.generated_at = timezone.now()
        report.save(update_fields=["file", "status", "generated_at"])
    except Exception as exc:  # noqa: BLE001 — record failure, don't crash caller
        report.status = Report.Status.FAILED
        report.error = str(exc)[:1000]
        report.save(update_fields=["status", "error"])
    return report
