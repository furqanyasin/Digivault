"""Post-save signals for Website — auto-provision monitors, status page, and kick off checks."""
from __future__ import annotations

import logging
import re

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender="websites.Website")
def on_website_created(sender, instance, created, **kwargs):
    if not created:
        return

    # Run synchronous DB-only work immediately, then queue network calls as tasks.
    monitor = _create_uptime_monitor_db_only(instance)
    _create_status_page(instance, monitor)

    # Defer all network I/O — each task runs in Celery worker.
    from apps.websites.tasks import run_initial_checks
    run_initial_checks.delay(str(instance.pk))


# ── helpers ───────────────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:80]


def _create_uptime_monitor_db_only(website):
    """Create the Monitor record only — no network call."""
    try:
        from apps.monitors.models import Monitor

        url = website.domain
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        monitor, _ = Monitor.objects.get_or_create(
            team=website.team,
            url=url,
            defaults={
                "name": website.name or website.domain,
                "monitor_type": Monitor.MonitorType.HTTP,
                "check_interval": 900,
                "timeout": 30,
                # retry_count is deliberately left to the model default (3).
                # This used to pin it to 1, which silently undid the retry
                # budget for every website ever added through the UI — one 403
                # from a WAF, one TCP reset, one slow DNS lookup and the client
                # got paged about a site that was serving visitors fine.
            },
        )
        if monitor.website_id != website.id:
            monitor.website = website
            monitor.save(update_fields=["website"])
        return monitor
    except Exception:
        logger.exception("Failed to auto-create monitor for %s", website.domain)
        return None


def _create_status_page(website, monitor) -> None:
    """Create a public status page for the website and add its uptime monitor.

    Idempotent per team + domain: if this team already has a status page for the
    domain (the base slug or any of its ``-N`` collision variants), we skip
    creating another one. This prevents duplicate pages when a site is re-added
    or exists as multiple Website rows for the same domain.
    """
    try:
        from django.db.models import Q

        from apps.status_pages.models import StatusPage, StatusPageMonitor

        base_slug = _slugify(
            website.domain.replace("https://", "").replace("http://", "")
        )

        # Already have a page for this domain on this team? Don't duplicate.
        existing = StatusPage.objects.filter(team=website.team).filter(
            Q(slug=base_slug) | Q(slug__regex=rf"^{re.escape(base_slug)}-\d+$")
        ).first()
        if existing is not None:
            if monitor:
                StatusPageMonitor.objects.get_or_create(
                    status_page=existing,
                    monitor=monitor,
                    defaults={"display_order": 0},
                )
            logger.info(
                "Status page for %s already exists on team; skipping create",
                website.domain,
            )
            return

        # Suffix loop only guards the model's global slug-uniqueness across teams.
        slug = base_slug
        counter = 1
        while StatusPage.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        page = StatusPage.objects.create(
            team=website.team,
            name=website.name or website.domain,
            slug=slug,
            description=f"Real-time status for {website.domain}",
            allow_indexing=False,
        )

        if monitor:
            StatusPageMonitor.objects.create(
                status_page=page,
                monitor=monitor,
                display_order=0,
            )

        logger.info("Auto-created status page '%s' for %s", slug, website.domain)
    except Exception:
        logger.exception("Failed to auto-create status page for %s", website.domain)


