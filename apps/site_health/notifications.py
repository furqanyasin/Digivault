"""Deliver SEO regression alerts to a team's notification channels."""
from __future__ import annotations

import json
import logging
import urllib.request

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def notify_team(team, subject: str, body: str) -> None:
    """Best-effort delivery to every active channel for the team."""
    from apps.monitors.models import NotificationChannel

    for ch in NotificationChannel.objects.filter(team=team, is_active=True):
        try:
            if ch.channel_type == "email":
                addrs = ch.config.get("addresses", [])
                if addrs:
                    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, addrs, fail_silently=True)
            elif ch.channel_type == "clickup":
                token, task_id = ch.config.get("api_token", ""), ch.config.get("task_id", "")
                if token and task_id:
                    data = json.dumps({"comment_text": f"**{subject}**\n{body}"}).encode()
                    req = urllib.request.Request(
                        f"https://api.clickup.com/api/v2/task/{task_id}/comment",
                        data=data,
                        headers={"Content-Type": "application/json", "Authorization": token},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=10).close()
        except Exception:
            logger.exception("SEO alert delivery failed via channel %s", ch.id)
