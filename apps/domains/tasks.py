"""Celery tasks for domain and SSL monitoring."""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.domains.models import DomainAlert, DomainInfo
from apps.domains.services import (
    DOMAIN_ALERT_THRESHOLDS,
    HOSTING_ALERT_THRESHOLDS,
    SSL_ALERT_THRESHOLDS,
    DomainIntelligenceService,
    check_smtp,
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

    # Mail (SMTP) health — best-effort, never blocks the domain check.
    smtp = check_smtp(website.domain)
    DomainInfo.objects.filter(pk=domain_info.pk).update(
        smtp_status=smtp["smtp_status"],
        mx_hosts=smtp["mx_hosts"],
        smtp_checked_at=timezone.now(),
    )

    _create_expiry_alerts(domain_info)
    _deliver_unsent_alerts(domain_info)
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
        (
            DomainAlert.AlertType.HOSTING,
            domain_info.hosting_expires_at,
            HOSTING_ALERT_THRESHOLDS,
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


def _deliver_unsent_alerts(domain_info: DomainInfo) -> None:
    """Deliver the most urgent unsent alert per type; mark superseded thresholds sent.

    A domain that is already close to expiry crosses several thresholds at once
    (30/14/7 days). Sending one message per threshold is noise — instead send the
    single most urgent one and treat the wider thresholds as covered by it.
    """
    from apps.domains.notifications import deliver_domain_alert

    for alert_type in (DomainAlert.AlertType.DOMAIN, DomainAlert.AlertType.SSL, DomainAlert.AlertType.HOSTING):
        unsent = list(
            domain_info.alerts.filter(sent=False, alert_type=alert_type)
            .order_by("days_until_expiry")
        )
        if not unsent:
            continue
        delivered = deliver_domain_alert(unsent[0])
        if delivered and len(unsent) > 1:
            DomainAlert.objects.filter(pk__in=[a.pk for a in unsent[1:]]).update(
                sent=True, sent_at=timezone.now()
            )


@shared_task(name="domains.check_all_domains")
def check_all_domains() -> int:
    """Scheduled daily task — enqueue a check_domain task per live website.

    Only 'inactive' is skipped. This used to also skip 'critical', which became a
    trap once status started deriving from health_score: a site whose score fell
    below 60 would stop receiving domain checks, so its expiry data froze and the
    expiry deductions could never clear. 'critical' means "needs attention" — the
    last status that should stop being checked.
    """
    ids = list(
        Website.objects.exclude(status=Website.Status.INACTIVE)
        .values_list("pk", flat=True)
    )
    for website_id in ids:
        check_domain.delay(str(website_id))
    logger.info("check_all_domains: queued %d checks", len(ids))
    return len(ids)
