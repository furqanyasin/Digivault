"""Outbound delivery of domain / SSL expiry alerts to a team's notification channels."""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.integrations.clickup import ClickUpClient

logger = logging.getLogger(__name__)


def _alert_message(alert) -> tuple[str, str]:
    """Return (subject, body) describing a DomainAlert."""
    domain_info = alert.domain_info
    website = domain_info.website
    if alert.alert_type == "ssl":
        kind = "SSL certificate"
        days = domain_info.ssl_days_until_expiry
    elif alert.alert_type == "hosting":
        kind = "Hosting plan"
        days = domain_info.hosting_days_until_expiry
    else:
        kind = "Domain registration"
        days = domain_info.domain_days_until_expiry

    label = website.name or website.domain
    days_txt = f"{days} days" if days is not None else f"{alert.days_until_expiry} days"
    subject = f"[Digivault] {kind} for {label} expires in {days_txt}"
    body = (
        f"{kind} for {label} ({website.domain}) expires in {days_txt}.\n\n"
        "Log in to Digivault to review and renew before it lapses."
    )
    return subject, body


def _send_email(channel, subject: str, body: str) -> None:
    addresses = channel.config.get("addresses", [])
    if not addresses:
        logger.warning("Email channel %s has no addresses", channel.id)
        return
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "alerts@digivault.digilatics.co")
    send_mail(subject, body, from_email, addresses, fail_silently=False)


def _send_clickup(channel, subject: str, body: str) -> None:
    api_token = channel.config.get("api_token", "")
    task_id = channel.config.get("task_id", "")
    if not api_token or not task_id:
        logger.warning("ClickUp channel %s missing api_token or task_id", channel.id)
        return
    ClickUpClient(api_token).comment(task_id, f"**{subject}**\n{body}")


_SENDERS = {
    "email": _send_email,
    "clickup": _send_clickup,
}


def _expiry_title(alert) -> str:
    kind = {
        "ssl": "SSL certificate",
        "hosting": "Hosting plan",
    }.get(alert.alert_type, "Domain registration")
    return f"{kind} expires in {alert.days_until_expiry} days"


def _announce_in_team_channel(alert, website, body: str) -> None:
    """Post an expiry alert into the team's ClickUp channel, best-effort.

    Wrapped rather than trusted: deliver_domain_alert decides whether the alert
    counts as sent, and a chat failure must not change that decision.
    """
    from apps.integrations import chat

    try:
        chat.notify_problem(
            website,
            subject=f"domain:{alert.domain_info_id}:{alert.alert_type}",
            title=_expiry_title(alert),
            detail=body,
            tags=["expiry"],
        )
    except Exception:
        logger.exception("Team channel announce failed for domain alert %s", alert.id)


def deliver_domain_alert(alert) -> bool:
    """Send one DomainAlert to every active channel for its team.

    Returns True (and marks the alert sent) if it reached at least one channel.
    Leaves the alert unsent if the team has no channels or every send failed,
    so a later domain check retries it.
    """
    from apps.monitors.notifications import resolve_channels

    website = alert.domain_info.website
    subject, body = _alert_message(alert)

    # The shared team channel is independent of configured channels — a team
    # with none still wants expiry in its feed.
    _announce_in_team_channel(alert, website, body)

    channels = resolve_channels(website)
    if not channels:
        logger.info("No active channels for %s; domain alert %s left unsent", website.domain, alert.id)
        return False

    delivered_any = False
    for channel in channels:
        sender = _SENDERS.get(channel.channel_type)
        if sender is None:
            continue
        try:
            sender(channel, subject, body)
            delivered_any = True
            logger.info(
                "Domain alert %s delivered via %s (%s)", alert.id, channel.name, channel.channel_type
            )
        except Exception:
            logger.exception("Domain alert %s delivery failed via %s", alert.id, channel.name)

    if delivered_any:
        alert.sent = True
        alert.sent_at = timezone.now()
        alert.save(update_fields=["sent", "sent_at"])
    return delivered_any
