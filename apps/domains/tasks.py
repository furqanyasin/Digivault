"""Celery tasks for domain and SSL monitoring."""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.domains.models import DomainAlert, DomainInfo
from apps.domains.services import (
    DOMAIN_ALERT_THRESHOLDS,
    SSL_ALERT_THRESHOLDS,
    DomainIntelligenceService,
)
from apps.websites.models import Website

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    name="domains.check_domain",
)
def check_domain(self, website_id: str) -> None:
    """Run WHOIS + hosting + SSL check for one website and persist results."""
    try:
        website = Website.objects.get(pk=website_id)
    except Website.DoesNotExist:
        return

    result = DomainIntelligenceService.check(website.domain)

    domain_info, _ = DomainInfo.objects.update_or_create(
        website=website,
        defaults={
            "registrar": result.registrar,
            "registered_at": result.registered_at,
            "expires_at": result.expires_at,
            "nameservers": result.nameservers,
            "whois_privacy": result.whois_privacy,
            "hosting_provider": result.hosting_provider,
            "hosting_ip": result.hosting_ip or None,
            "uses_cloudflare": result.uses_cloudflare,
            "ssl_issuer": result.ssl_issuer,
            "ssl_expires_at": result.ssl_expires_at,
            "ssl_auto_renew": result.ssl_auto_renew,
            "last_checked_at": timezone.now(),
        },
    )

    _create_expiry_alerts(domain_info)
    website.recalculate_health_score()


def _create_expiry_alerts(domain_info: DomainInfo) -> None:
    """Create DomainAlert records for crossed expiry thresholds."""
    now = timezone.now()

    for alert_type, expires_at, thresholds in (
        (
            DomainAlert.AlertType.DOMAIN,
            domain_info.expires_at,
            DOMAIN_ALERT_THRESHOLDS,
        ),
        (
            DomainAlert.AlertType.SSL,
            domain_info.ssl_expires_at,
            SSL_ALERT_THRESHOLDS,
        ),
    ):
        if not expires_at:
            continue
        days_left = max(0, (expires_at - now).days)
        for threshold in thresholds:
            if days_left <= threshold:
                DomainAlert.objects.get_or_create(
                    domain_info=domain_info,
                    alert_type=alert_type,
                    days_until_expiry=threshold,
                    defaults={"sent": False},
                )


@shared_task(name="domains.check_all_domains")
def check_all_domains() -> int:
    """Scheduled daily task — enqueue a check_domain task per active website."""
    ids = list(
        Website.objects.filter(status__in=[Website.Status.ACTIVE, Website.Status.WARNING])
        .values_list("pk", flat=True)
    )
    for website_id in ids:
        check_domain.delay(str(website_id))
    logger.info("check_all_domains: queued %d checks", len(ids))
    return len(ids)
