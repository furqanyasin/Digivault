"""Celery tasks for website post-creation work."""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.common import outbound

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

    Deliberately **not** narrowed to sites with the snippet installed, which is
    what it used to do. Every deduction this sweep exists to decay — domain,
    SSL and hosting expiry — is discovered server-side and applies just as much
    to a site that has never carried the snippet. Uptime monitoring, passive
    scans and SEO checks all start the moment a Website is created, so a
    snippet-less site accrues findings from day one; gating the recalculation on
    `snippet_status=INSTALLED` meant those sites were the only ones whose score
    could never move, and an expiring certificate on one of them was invisible
    until somebody opened the page.
    """
    from apps.websites.models import Website

    count = 0
    for website in Website.objects.filter(
        status__in=[Website.Status.ACTIVE, Website.Status.WARNING, Website.Status.CRITICAL],
    ).iterator():
        try:
            website.recalculate_health_score()
            count += 1
        except Exception:
            logger.exception("recalculate_all_health failed for website %s", website.pk)
    logger.info("recalculate_all_health: recalculated %d websites", count)
    return count


# `websites.sync_wp_form_recipients` used to live here, named for the WP
# Connect route it was written against. That route was retired, and the task was
# repointed at `wp_api_forms.sync_website` — the same function
# `sync_wp_api_form_recipients` below already calls. Two beat entries then ran
# the identical sweep an hour apart, and the older one had never grown the
# guard the newer one exists around: it did not skip sites whose credential had
# already been rejected, so it spent every morning re-presenting a known-bad
# Application Password from our single egress IP. Repeated 401s are how that IP
# gets banned, and a ban costs uptime monitoring for every client — which is
# the entire reason `wp_api_auth_failed_at` was added.
#
# Deleting a named task means a message already queued under the old name will
# be rejected as unregistered once. That is a one-deploy cost, not a recurring
# one, and it is cheaper than a sweep nobody knew was running.


@shared_task(name="websites.sync_wp_api_form_recipients")
def sync_wp_api_form_recipients(website_pk: str | None = None) -> int:
    """Read form recipients from sites' own WordPress APIs. Returns rows written.

    The WP-Connect-free path, covering Elementor and Gravity Forms only — see
    `apps.websites.wp_api_forms` for why the other two plugins cannot be read.

    Skips sites with no detected forms (nothing to join an answer onto) and
    sites whose credential was already rejected (`wp_api_auth_failed_at`).
    """
    from apps.websites.models import Website
    from apps.websites.wp_api_forms import sync_website

    sites = Website.objects.exclude(status=Website.Status.INACTIVE).filter(
        wp_api_auth_failed_at__isnull=True
    )
    if website_pk:
        sites = sites.filter(pk=website_pk)
    sites = sites.filter(detected_forms__isnull=False).distinct()

    written = 0
    for website in sites.iterator():
        try:
            written += sync_website(website)
        except Exception:
            logger.exception("sync_wp_api_form_recipients failed for %s", website.pk)
    logger.info("sync_wp_api_form_recipients: updated %d form(s)", written)
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


# How stale a server-side scan may get before we look again. Daily: script tags
# change when someone edits the site, which is not an hourly event, and one
# request per site per day is a rounding error next to the uptime monitor.
_PASSIVE_SCAN_MAX_AGE = timezone.timedelta(hours=20)


@shared_task(name="websites.run_due_passive_scans")
def run_due_passive_scans() -> int:
    """Queue a server-side script scan for every site that has not had one today.

    It runs only after a browser has reported the tracking snippet. The snippet
    is the activation signal for script-dependent processing; this scan remains
    a static homepage supplement and does not replace runtime collection.
    """
    from apps.site_health.models import SiteScanState
    from apps.websites.models import Website

    cutoff = timezone.now() - _PASSIVE_SCAN_MAX_AGE
    enqueued = 0
    for website in Website.objects.filter(
        status__in=[Website.Status.ACTIVE, Website.Status.WARNING, Website.Status.CRITICAL],
        snippet_status=Website.SnippetStatus.INSTALLED,
    ).iterator():
        state = SiteScanState.objects.filter(website=website).first()
        if state and state.last_scanned_at and state.last_scanned_at > cutoff:
            continue
        passive_scan_website.delay(str(website.pk))
        enqueued += 1

    logger.info("run_due_passive_scans: queued %d site(s)", enqueued)
    return enqueued


@shared_task(name="websites.passive_scan_website")
def passive_scan_website(website_pk: str) -> None:
    """Fetch one homepage server-side and feed it to the normal ingest pipeline."""
    from apps.scripts.models import ScriptSnapshot
    from apps.scripts.tasks import process_ingest_payload
    from apps.site_health.models import SiteScanState
    from apps.websites.models import Website
    from apps.websites.platform_detect import detect_platform
    from apps.websites.views import _extract_forms, _extract_script_urls

    try:
        website = Website.objects.get(pk=website_pk)
    except Website.DoesNotExist:
        return

    if website.snippet_status != Website.SnippetStatus.INSTALLED:
        logger.info("passive scan: %s skipped until snippet reports", website.domain)
        return

    url = website.domain
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    state, _ = SiteScanState.objects.get_or_create(website=website)

    # No cache-buster here, unlike the human-triggered scan. A random query
    # string forces an origin hit on every request and is exactly what reads as
    # scanning to a WAF; for a daily background sweep a CDN-cached copy of the
    # homepage tells us everything we need about its script tags.
    try:
        result = outbound.fetch(url, timeout=20, wait_up_to=30, read_bytes=2_000_000)
    except Exception as exc:
        logger.info("passive scan: %s unreachable: %s", website.domain, exc)
        state.error = str(exc)[:500]
        state.save(update_fields=["error"])
        return

    vendor = result.blocked_by
    if vendor or result.status_code >= 400:
        # Critically, this does NOT write an empty script list. A block page
        # contains no <script src> tags, and treating that as an observation
        # would report the client's entire third-party stack as removed.
        reason = (
            f"Blocked by {vendor} (HTTP {result.status_code})"
            if vendor
            else f"HTTP {result.status_code}"
        )
        logger.info("passive scan: %s → %s", website.domain, reason)
        state.error = reason[:500]
        state.save(update_fields=["error"])
        return

    detected = detect_platform(result.body, result.headers)
    if detected and detected != website.platform:
        website.platform = detected
        website.save(update_fields=["platform"])

    script_urls = _extract_script_urls(result.body)
    forms = _extract_forms(result.body)

    state.last_scanned_at = timezone.now()
    state.error = ""
    state.save(update_fields=["last_scanned_at", "error"])

    if not script_urls and not forms:
        logger.info("passive scan: %s has no external scripts or forms", website.domain)
        return

    process_ingest_payload.delay(website.site_id, {
        "page_url": result.final_url,
        "scripts": [
            {"src": src, "location": "unknown", "async": False,
             "defer": False, "inline": False}
            for src in script_urls
        ],
        "forms": forms,
        "user_agent": "StacksMonitor-Scanner/1.0",
        "snippet_version": ScriptSnapshot.SERVER_SCAN_VERSION,
    })
    logger.info(
        "passive scan: %s → %d scripts, %d forms",
        website.domain, len(script_urls), len(forms),
    )
