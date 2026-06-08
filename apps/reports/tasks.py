"""Celery tasks for report generation."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="reports.generate_for_website")
def generate_for_website(website_id: str, start: str, end: str, fmt: str = "pdf") -> str | None:
    """Generate one report asynchronously. Returns the Report id (or None)."""
    import datetime

    from apps.reports.services import generate_report
    from apps.websites.models import Website

    try:
        website = Website.objects.get(pk=website_id)
    except Website.DoesNotExist:
        return None

    report = generate_report(
        website,
        datetime.date.fromisoformat(start),
        datetime.date.fromisoformat(end),
        report_format=fmt,
    )
    return str(report.pk)


@shared_task(name="reports.generate_monthly")
def generate_monthly() -> int:
    """Generate a PDF report for every active website covering the previous month."""
    import datetime

    from apps.reports.services import generate_report
    from apps.websites.models import Website

    today = datetime.date.today()
    first_this_month = today.replace(day=1)
    last_prev = first_this_month - datetime.timedelta(days=1)
    first_prev = last_prev.replace(day=1)

    count = 0
    for website in Website.objects.filter(status="active").iterator():
        generate_report(website, first_prev, last_prev, report_format="pdf")
        count += 1

    logger.info("reports.generate_monthly: generated %d reports", count)
    return count
