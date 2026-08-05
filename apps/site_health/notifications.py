"""Deliver SEO regression alerts to a team's notification channels."""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

from apps.integrations.clickup import ClickUpClient

logger = logging.getLogger(__name__)


def notify_team(website, subject: str, body: str, *, subject_key: str = "") -> None:
    """Best-effort delivery to the website's notification channel (or the team's
    active channels when the site has none set), plus the shared team channel.

    `subject_key` is the stable issue key for ClickUp task dedup. It is optional
    because the alert subject line embeds changing detail — without a key, one
    task per distinct wording would pile up, so the chat post is skipped instead.
    """
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

    if not subject_key:
        return

    from apps.integrations import chat

    try:
        chat.notify_problem(
            website,
            subject=subject_key,
            # The "[Digivault] " prefix is email framing; the channel already
            # knows who is talking.
            title=subject.replace("[Digivault] ", ""),
            detail=body,
            tags=["seo"],
        )
    except Exception:
        logger.exception("Team channel announce failed for %s", website.domain)
