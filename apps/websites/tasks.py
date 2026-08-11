"""Celery tasks for website post-creation work."""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="websites.run_initial_checks", max_retries=2, default_retry_delay=30)
def run_initial_checks(website_pk: str) -> None:
    """Run uptime check, domain check, and performance check for a newly created website.

    Deferred from the post_save signal so the HTTP response returns immediately.
    """
    from apps.websites.models import Website

    try:
        website = Website.objects.select_related("team").get(pk=website_pk)
    except Website.DoesNotExist:
        logger.warning("run_initial_checks: website %s not found", website_pk)
        return

    _run_uptime_check(website)
    _run_domain_check(website)
    _run_performance_check(website)


@shared_task(name="websites.recalculate_all_health")
def recalculate_all_health() -> int:
    """Nightly sweep so time-based health deductions actually decay.

    Several deductions are functions of elapsed time — domain/SSL/hosting expiry
    windows and the last_seen_at reporting gap. Event triggers (ingest,
    acknowledge, monitor flip, domain check) never fire for a site that has
    simply gone quiet, so without this sweep a site could drift past an expiry
    date while still reporting yesterday's score. Idempotent.
    """
    from apps.websites.models import Website

    count = 0
    for website in Website.objects.exclude(status=Website.Status.INACTIVE).iterator():
        try:
            website.recalculate_health_score()
            count += 1
        except Exception:
            logger.exception("recalculate_all_health failed for website %s", website.pk)
    logger.info("recalculate_all_health: recalculated %d websites", count)
    return count


@shared_task(name="websites.sync_wp_form_recipients")
def sync_wp_form_recipients(website_pk: str | None = None) -> int:
    """Ask WP Connect sites where their forms deliver. Returns rows written.

    Skips sites with no snippet secret and sites with no detected forms — there
    is nothing to sign a request with, or nothing to join the answer onto.
    """
    from apps.websites.models import Website
    from apps.websites.wp_forms import sync_website

    sites = Website.objects.exclude(wp_sso_secret="").exclude(
        status=Website.Status.INACTIVE
    )
    if website_pk:
        sites = sites.filter(pk=website_pk)
    sites = sites.filter(detected_forms__isnull=False).distinct()

    written = 0
    for website in sites.iterator():
        try:
            written += sync_website(website)
        except Exception:
            logger.exception("sync_wp_form_recipients failed for %s", website.pk)
    logger.info("sync_wp_form_recipients: updated %d form(s)", written)
    return written


def _run_uptime_check(website) -> None:
    try:
        from apps.monitors.models import Monitor, MonitorCheck
        from apps.monitors.checker import run_check

        url = website.domain
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        monitor = Monitor.objects.filter(team=website.team, url=url).first()
        if not monitor:
            return

        result = run_check(monitor)
        new_status = result["status"]
        MonitorCheck.objects.create(
            monitor=monitor,
            status=new_status,
            response_time_ms=result.get("response_time_ms"),
            status_code=result.get("status_code"),
            error_message=result.get("error_message", ""),
        )
        Monitor.objects.filter(pk=monitor.pk).update(
            status=new_status,
            last_checked_at=timezone.now(),
            last_response_time=result.get("response_time_ms"),
        )
        monitor.refresh_from_db()
        monitor.recalculate_uptime()
        logger.info("Initial uptime check for %s: %s", website.domain, new_status)
    except Exception:
        logger.exception("Uptime check failed for %s", website.domain)


def _run_domain_check(website) -> None:
    try:
        from apps.domains.views import _persist_domain_check
        _persist_domain_check(website)
        logger.info("Domain check completed for %s", website.domain)
    except Exception:
        logger.exception("Domain check failed for %s", website.domain)


def _run_performance_check(website) -> None:
    try:
        from apps.performance.services import PageSpeedService
        from apps.performance.models import PerformanceReport

        url = website.domain
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        result = PageSpeedService.check(url, strategy="mobile")
        PerformanceReport.objects.create(
            website=website,
            url=url,
            strategy="mobile",
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
        logger.info("Performance check completed for %s", website.domain)
    except Exception:
        logger.exception("Performance check failed for %s", website.domain)
