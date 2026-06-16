"""Celery tasks for script processing.

The ingest view accepts the HTTP request immediately (202 Accepted) and
delegates all heavy work here so the snippet endpoint stays under 50ms.
"""

from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urlparse

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.scripts.classifier import ScriptClassifier
from apps.scripts.diff_engine import DiffEngine
from apps.scripts.models import DetectedForm, Script, ScriptChange, ScriptSnapshot
from apps.websites.models import Website

# ---------------------------------------------------------------------------
# Script noise filter
# ---------------------------------------------------------------------------

# CDN domains that host only utility libraries — never marketing/analytics.
_UTILITY_CDN_BLOCKLIST: frozenset[str] = frozenset({
    "cdnjs.cloudflare.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "code.jquery.com",
    "maxcdn.bootstrapcdn.com",
    "stackpath.bootstrapcdn.com",
    "ajax.googleapis.com",       # jQuery CDN (GA uses google-analytics.com)
    "ajax.aspnetcdn.com",
    # Review / widget platforms — not analytics
    "cdn.trustindex.io",
    "cdn.elfsight.com",
    "apps.elfsight.com",
    "elfsight-cdn.com",
})

# Filename patterns for utility libraries.  Only applied when the provider
# is already "unknown" so we never accidentally drop a real analytics script.
_UTILITY_FILENAME_RE: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"jquery[.\-]",
        r"/jquery\.js",
        r"bootstrap[.\-]",
        r"slick[.\-]",
        r"webpack[.\-]",
        r"\.chunk\.",
        r"runtime[.\-]",
        r"vendors?[.\-]",
        r"lodash[.\-]",
        r"underscore[.\-]",
        r"modernizr[.\-]",
        r"popper[.\-]",
        r"magnific",
        r"v\d+-shims",
        r"fontawesome|font-awesome",
        r"lazysizes",
        r"swiper[.\-]",
        r"owl\.carousel",
        r"customslick",
        r"/utils\.",
    )
)


def _internal_hosts() -> frozenset[str]:
    """Digivault's own infra hosts — the tracking snippet and dashboard.

    These must never be tracked as third-party scripts on a client site: the
    snippet (`/api/s.js`) is served from here, so the page reports it like any
    other script and it would otherwise log a high-severity "added" change that
    the UI hides (internal domain) yet which pins the site to 'critical'.
    """
    hosts = {
        "digivault.digilatics.co",
        "cdn.digivault.digilatics.co",
        "digilaticsvps.digilatics.co",
    }
    cdn = getattr(settings, "SNIPPET_CDN_URL", "") or ""
    host = urlparse(cdn).netloc.lower().removeprefix("www.")
    if host:
        hosts.add(host)
    return frozenset(hosts)


def _should_track_script(src: str, website_domain: str) -> bool:
    """Return False for self-hosted scripts, Digivault infra, and utility noise."""
    # Relative URLs are always self-hosted.
    if not src.startswith(("http://", "https://", "//")):
        return False

    parsed = urlparse(src if not src.startswith("//") else "https:" + src)
    script_host = parsed.netloc.lower().removeprefix("www.")

    # Digivault's own snippet / dashboard — never a client's third-party script.
    if script_host in _internal_hosts():
        return False

    # Normalise the site domain to bare hostname.
    site = website_domain
    if site.startswith(("http://", "https://")):
        site = urlparse(site).netloc
    site = site.lower().removeprefix("www.")

    # Self-hosted: same domain or any subdomain of the site.
    if script_host == site or script_host.endswith("." + site):
        return False

    # Known utility CDNs — never analytics.
    if script_host in _UTILITY_CDN_BLOCKLIST:
        return False

    # Utility filename patterns — only filter when provider is unknown so we
    # never accidentally drop a real (but unrecognised) analytics script.
    if ScriptClassifier.classify(src).provider == "unknown":
        path = parsed.path.lower()
        if any(pat.search(path) for pat in _UTILITY_FILENAME_RE):
            return False

    return True

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="scripts.process_ingest_payload",
)
def process_ingest_payload(self, site_id: str, payload: dict) -> None:
    """Process a snippet ingest payload.

    Steps:
    1. Resolve website by site_id.
    2. Save ScriptSnapshot.
    3. Retrieve the previous snapshot for the same page_url.
    4. Run the diff engine.
    5. Upsert Script records.
    6. Persist ScriptChange records.
    7. Touch website.last_seen_at.
    """
    try:
        website = Website.objects.get(site_id=site_id)
    except Website.DoesNotExist:
        logger.warning("process_ingest_payload: unknown site_id %s", site_id)
        return

    page_url: str = payload["page_url"]
    scripts_data: list[dict] = payload.get("scripts", [])

    def _is_trackable(s: dict) -> bool:
        src = s.get("src", "")
        if not src:
            return False
        if "/wp-includes/" in src or "/wp-admin/" in src:
            return False
        return _should_track_script(src, website.domain)

    try:
        with transaction.atomic():
            # --- 1. Save snapshot (raw — unfiltered for audit purposes) ---
            snapshot = ScriptSnapshot.objects.create(
                website=website,
                page_url=page_url,
                scripts_data=scripts_data,
                user_agent=payload.get("user_agent", ""),
                snippet_version=payload.get("snippet_version", ""),
            )

            # --- 2. Get previous snapshot for same page ---
            previous_snapshot = (
                ScriptSnapshot.objects.filter(
                    website=website, page_url=page_url
                )
                .exclude(pk=snapshot.pk)
                .order_by("-captured_at")
                .first()
            )
            raw_previous = previous_snapshot.scripts_data if previous_snapshot else []

            # Filter both lists to only third-party analytics/marketing scripts
            # before diffing — self-hosted and utility library changes are noise.
            trackable_current = [s for s in scripts_data if _is_trackable(s)]
            trackable_previous = [s for s in raw_previous if _is_trackable(s)]

            # --- 3. Run diff engine on filtered lists ---
            changes = DiffEngine.diff(trackable_previous, trackable_current)

            # --- 4. Upsert Script records ---
            for script_data in trackable_current:
                _upsert_script(website, script_data, page_url)

            # Collect ALL noise script PKs BEFORE any deactivation runs.
            # If we queried is_active=True after the GLOBAL step below, scripts
            # already deactivated there would be missed and their changes never
            # acknowledged, leaving the status stuck at critical.
            all_noise_pks = [
                s.pk
                for s in Script.objects.filter(website=website).only("pk", "src_url")
                if not _should_track_script(s.src_url, website.domain)
            ]

            # Mark scripts not seen in this snapshot as inactive
            # (only for scripts scoped globally — page-specific is handled separately)
            current_urls = {s["src"] for s in trackable_current}
            Script.objects.filter(
                website=website,
                scope=Script.Scope.GLOBAL,
                is_active=True,
            ).exclude(src_url__in=current_urls).update(is_active=False)

            # Deactivate noise scripts and auto-acknowledge their changes.
            if all_noise_pks:
                Script.objects.filter(pk__in=all_noise_pks, is_active=True).update(is_active=False)
                ScriptChange.objects.filter(
                    website=website,
                    script_id__in=all_noise_pks,
                    acknowledged_at__isnull=True,
                ).update(acknowledged_at=timezone.now())

            # --- 5. Persist ScriptChange records ---
            for change in changes:
                script_obj = None
                if change.src_url:
                    script_obj = Script.objects.filter(
                        website=website, src_url=change.src_url
                    ).first()
                ScriptChange.objects.create(
                    website=website,
                    script=script_obj,
                    change_type=change.change_type,
                    severity=change.severity,
                    description=change.description,
                    old_value=change.old_value,
                    new_value=change.new_value,
                )

            # --- 5b. Dispatch alert notifications for each change ---
            from apps.alerts.services import AlertService
            from apps.alerts.tasks import deliver_notification

            for change_record in ScriptChange.objects.filter(
                website=website,
                created_at__gte=snapshot.captured_at,
            ):
                notifications = AlertService.dispatch_for_change(change_record)
                for notif in notifications:
                    if notif.rule and notif.rule.delivery_mode == "immediate":
                        deliver_notification.delay(str(notif.pk))

            # --- 6. Upsert detected forms ---
            for form_data in payload.get("forms", []):
                _upsert_form(website, page_url, form_data)

            # --- 7. Update scope labels ---
            _update_script_scopes(website)

            # --- 7. Touch website ---
            website.last_seen_at = timezone.now()
            website.save(update_fields=["last_seen_at"])

            # Always recalculate — noise cleanup may have shifted the status
            # even when no new trackable changes occurred.
            _update_website_status(website)
            website.recalculate_health_score()

    except Exception as exc:
        logger.exception("process_ingest_payload failed for site_id=%s", site_id)
        raise self.retry(exc=exc)


def _upsert_script(website: Website, script_data: dict, page_url: str) -> Script:
    """Create or update a Script record from one snippet script entry."""
    src = script_data["src"]
    classification = ScriptClassifier.classify(src)
    domain = ScriptClassifier.extract_domain(src)

    script, created = Script.objects.get_or_create(
        website=website,
        src_url=src,
        defaults={
            "src_domain": domain,
            "provider": classification.provider,
            "category": classification.category,
            "location": script_data.get("location", Script.Location.UNKNOWN),
            "is_async": script_data.get("is_async", False),
            "is_defer": script_data.get("is_defer", False),
            "is_inline": script_data.get("is_inline", False),
            "inline_hash": script_data.get("inline_hash", ""),
            "wp_plugin": script_data.get("wp_plugin", ""),
            "wp_post_id": script_data.get("wp_post_id"),
            "seen_on_pages": [page_url],
        },
    )

    if not created:
        # Update mutable fields and keep seen_on_pages current
        seen = script.seen_on_pages or []
        if page_url not in seen:
            seen.append(page_url)
        Script.objects.filter(pk=script.pk).update(
            is_active=True,
            src_domain=domain,
            provider=classification.provider,
            category=classification.category,
            location=script_data.get("location", script.location),
            is_async=script_data.get("is_async", script.is_async),
            is_defer=script_data.get("is_defer", script.is_defer),
            wp_plugin=script_data.get("wp_plugin", script.wp_plugin) or script.wp_plugin,
            seen_on_pages=seen,
        )

    return script


def _upsert_form(website, page_url: str, form_data: dict) -> None:
    fingerprint = DetectedForm.compute_fingerprint(form_data)
    DetectedForm.objects.update_or_create(
        website=website,
        page_url=page_url,
        fingerprint=fingerprint,
        defaults={
            "form_id": form_data.get("form_id", ""),
            "form_name": form_data.get("form_name", ""),
            "form_action": form_data.get("form_action", ""),
            "form_method": (form_data.get("form_method") or "post").lower(),
            "detection_type": form_data.get(
                "detection_type", DetectedForm.DetectionType.NATIVE
            ),
            "provider": form_data.get("provider", ""),
            "fields": form_data.get("fields", []),
        },
    )


def _update_script_scopes(website: Website) -> None:
    """Classify each active script as GLOBAL, PAGE_SPECIFIC, or ONE_TIME.

    Rules (per PDF §9.2):
    - Seen on ≥80% of all known pages → GLOBAL
    - Seen on <80% of pages (but >1 page) → PAGE_SPECIFIC
    - Seen on exactly 1 page → ONE_TIME (flag unknown scripts for review)
    """
    total_pages = (
        ScriptSnapshot.objects.filter(website=website)
        .values("page_url")
        .distinct()
        .count()
    )
    if total_pages == 0:
        return

    scripts = Script.objects.filter(website=website, is_active=True)
    for script in scripts:
        seen_count = len(set(script.seen_on_pages or []))

        if seen_count <= 1:
            new_scope = Script.Scope.ONE_TIME
        elif total_pages == 1 or seen_count / total_pages >= 0.8:
            new_scope = Script.Scope.GLOBAL
        else:
            new_scope = Script.Scope.PAGE_SPECIFIC

        if script.scope != new_scope:
            Script.objects.filter(pk=script.pk).update(scope=new_scope)
            # Flag one-time unknown scripts for review
            if new_scope == Script.Scope.ONE_TIME and script.provider == "unknown":
                Script.objects.filter(pk=script.pk).update(
                    review_status=Script.ReviewStatus.PENDING
                )


def _update_website_status(website: Website) -> None:
    """Set website status from open changes the user can actually see and clear.

    Changes on Digivault's own infra domains (e.g. the tracking snippet) are
    hidden from the Change Log, so they must not drive the status — otherwise a
    site shows 'critical' with nothing the user can acknowledge.
    """
    internal = _internal_hosts()

    def _is_internal(change) -> bool:
        blob = f"{change.script.src_url if change.script_id else ''} {change.description or ''}".lower()
        return any(host in blob for host in internal)

    open_changes = (
        ScriptChange.objects.filter(website=website, acknowledged_at__isnull=True)
        .select_related("script")
    )
    severities = {c.severity for c in open_changes if not _is_internal(c)}

    if ScriptChange.Severity.HIGH in severities:
        new_status = Website.Status.CRITICAL
    elif ScriptChange.Severity.MEDIUM in severities:
        new_status = Website.Status.WARNING
    else:
        new_status = Website.Status.ACTIVE

    Website.objects.filter(pk=website.pk).update(status=new_status)


@shared_task(name="scripts.purge_old_snapshots")
def purge_old_snapshots() -> int:
    """Delete ScriptSnapshot records older than 90 days.  Chunked to avoid
    long-running transactions.  Scheduled via Celery Beat weekly.
    """
    from django.utils.timezone import timedelta

    cutoff = timezone.now() - timedelta(days=90)
    total_deleted = 0
    chunk_size = 500

    while True:
        ids = list(
            ScriptSnapshot.objects.filter(captured_at__lt=cutoff)
            .values_list("pk", flat=True)[:chunk_size]
        )
        if not ids:
            break
        deleted, _ = ScriptSnapshot.objects.filter(pk__in=ids).delete()
        total_deleted += deleted

    logger.info("purge_old_snapshots: removed %d snapshots", total_deleted)
    return total_deleted
