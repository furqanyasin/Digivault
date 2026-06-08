"""Celery tasks for website performance monitoring."""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=30, name="performance.check_website_performance")
def check_website_performance(self, website_id: str, strategy: str = "mobile") -> None:
    from apps.performance.models import PerformanceReport
    from apps.performance.services import PageSpeedService
    from apps.websites.models import Website

    try:
        website = Website.objects.get(pk=website_id)
    except Website.DoesNotExist:
        return

    url = website.domain
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    result = PageSpeedService.check(url, strategy=strategy)

    PerformanceReport.objects.create(
        website=website,
        url=url,
        strategy=strategy,
        performance_score=result.performance_score,
        fcp_ms=result.fcp_ms,
        lcp_ms=result.lcp_ms,
        cls_score=result.cls_score,
        tbt_ms=result.tbt_ms,
        ttfb_ms=result.ttfb_ms,
        si_ms=result.si_ms,
        tti_ms=result.tti_ms,
        inp_ms=result.inp_ms,
        fcp_rating=result.fcp_rating,
        lcp_rating=result.lcp_rating,
        cls_rating=result.cls_rating,
        tbt_rating=result.tbt_rating,
        error=result.error,
    )

    logger.info(
        "Performance %s (%s): score=%s fcp=%s lcp=%s",
        website.domain, strategy, result.performance_score, result.fcp_ms, result.lcp_ms,
    )

    if not result.error:
        from apps.performance.trends import alert_on_regression
        alert_on_regression(website, strategy)


@shared_task(name="performance.purge_old_reports")
def purge_old_reports(days: int = 365) -> int:
    """Delete PerformanceReport rows older than `days` (default 12 months). Chunked."""
    from apps.performance.models import PerformanceReport

    cutoff = timezone.now() - timezone.timedelta(days=days)
    total = 0
    chunk = 1000
    while True:
        ids = list(
            PerformanceReport.objects.filter(checked_at__lt=cutoff).values_list(
                "pk", flat=True
            )[:chunk]
        )
        if not ids:
            break
        deleted, _ = PerformanceReport.objects.filter(pk__in=ids).delete()
        total += deleted

    logger.info("performance.purge_old_reports: removed %d rows", total)
    return total
