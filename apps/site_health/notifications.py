"""Deliver SEO regression alerts to a team's notification channels."""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

from apps.integrations.clickup import ClickUpClient

logger = logging.getLogger(__name__)


def notify_team(website, subject: str, body: str) -> None:
    """Best-effort delivery to the website's notification channel (or the team's
    active channels when the site has none set)."""
    from apps.monitors.notifications import resolve_channels

    for ch in resolve_channels(website):
        try:
            if ch.channel_type == "email":
                addrs = ch.config.get("addresses", [])
                if addrs:
                    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, addrs, fail_silently=True)
            elif ch.channel_type == "clickup":
                token, task_id = ch.config.get("api_token", ""), ch.config.get("task_id", "")
                if token and task_id:
                    ClickUpClient(token).comment(task_id, f"**{subject}**\n{body}")
        except Exception:
            logger.exception("SEO alert delivery failed via channel %s", ch.id)
