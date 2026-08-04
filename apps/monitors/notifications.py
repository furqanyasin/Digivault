"""Outbound notification delivery for uptime monitor status changes.

Each dispatcher is a small stateless function that accepts a monitor,
the old status, the new status, and the NotificationChannel record.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import TYPE_CHECKING

from apps.integrations.clickup import ClickUpClient

if TYPE_CHECKING:
    from apps.monitors.models import Monitor, NotificationChannel

logger = logging.getLogger(__name__)

STATUS_EMOJI = {
    "up": "✅",
    "down": "🔴",
    "degraded": "🟡",
    "pending": "⏳",
    "paused": "⏸️",
}


def _summary(monitor, old_status: str, new_status: str) -> str:
    emoji = STATUS_EMOJI.get(new_status, "")
    return f"{emoji} *{monitor.name}* is {new_status.upper()} (was {old_status})\n`{monitor.url}`"


# ------------------------------------------------------------------
# Channel-specific senders
# ------------------------------------------------------------------

def _send_email(channel, monitor, old_status: str, new_status: str) -> None:
    from django.conf import settings
    from django.core.mail import send_mail

    addresses = channel.config.get("addresses", [])
    if not addresses:
        logger.warning("Email channel %s has no addresses", channel.id)
        return
    subject = f"[Digivault] {monitor.name} is {new_status.upper()}"
    body = (
        f"Monitor: {monitor.name}\n"
        f"URL: {monitor.url}\n"
        f"Status changed: {old_status} → {new_status}\n\n"
        "Log in to Digivault to view details."
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "alerts@digivault.digilatics.co")
    try:
        send_mail(subject, body, from_email, addresses, fail_silently=False)
    except Exception:
        logger.exception("Email delivery failed for channel %s", channel.id)
        raise


# Matches a ClickUp Chat channel link, e.g.
# https://digilatics.clickup.com/25658037/chat/r/rf0nn-49438
_CLICKUP_CHAT_RE = re.compile(r"clickup\.com/(\d+)/chat/(?:r/)?([^/?#]+)", re.I)


def parse_clickup_chat(url: str) -> tuple[str | None, str | None]:
    """Return (workspace_id, channel_id) from a ClickUp Chat channel link."""
    m = _CLICKUP_CHAT_RE.search(url or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def post_clickup(config: dict, text: str) -> bool:
    """Post `text` to a ClickUp target. Prefers a Chat channel (v3 API) when the
    config has a `chat_url`; otherwise comments on a `task_id` (v2). Returns True
    if a request was sent, False if the config has no usable target. Raises
    ClickUpError on a non-2xx response so callers can log/retry."""
    config = config or {}
    api_token = config.get("api_token", "")
    if not api_token:
        return False

    api = ClickUpClient(api_token)

    chat_url = config.get("chat_url", "")
    if chat_url:
        ws, ch = parse_clickup_chat(chat_url)
        if ws and ch:
            api.post_chat(ws, ch, text)
            return True

    task_id = config.get("task_id", "")
    if task_id:
        api.comment(task_id, text)
        return True

    return False


def _send_clickup(channel, monitor, old_status: str, new_status: str) -> None:
    emoji = STATUS_EMOJI.get(new_status, "")
    text = (
        f"{emoji} **{monitor.name}** status changed: {old_status.upper()} → {new_status.upper()}\n"
        f"URL: {monitor.url}"
    )
    if not post_clickup(channel.config, text):
        logger.warning("ClickUp channel %s has no api_token or target", channel.id)


def _send_slack(channel, monitor, old_status: str, new_status: str) -> None:
    webhook_url = channel.config.get("webhook_url", "")
    if not webhook_url:
        logger.warning("Slack channel %s missing webhook_url", channel.id)
        return
    _http_post(
        webhook_url,
        {"text": _summary(monitor, old_status, new_status)},
        name="Slack",
    )


# ------------------------------------------------------------------
# Dispatcher registry
# ------------------------------------------------------------------

_SENDERS = {
    "email": _send_email,
    "clickup": _send_clickup,
    "slack": _send_slack,
}


def dispatch(channel: "NotificationChannel", monitor: "Monitor", old_status: str, new_status: str) -> None:
    sender = _SENDERS.get(channel.channel_type)
    if sender is None:
        logger.warning("No sender for channel type %s", channel.channel_type)
        return
    try:
        sender(channel, monitor, old_status, new_status)
        logger.info(
            "Notification sent via %s (%s) for monitor %s: %s → %s",
            channel.name, channel.channel_type, monitor.name, old_status, new_status,
        )
    except Exception:
        logger.exception(
            "Notification delivery failed via %s (%s) for monitor %s",
            channel.name, channel.channel_type, monitor.name,
        )


def resolve_channels(website):
    """The notification channels a website's alerts route to: its own channel if
    set + active, otherwise the team's active channels. Used by uptime, domain
    and SEO alerts so 'one channel per website' covers everything."""
    from apps.monitors.models import NotificationChannel

    if website is not None and getattr(website, "notification_channel_id", None):
        ch = website.notification_channel
        if ch and ch.is_active:
            return [ch]
    team = getattr(website, "team", None)
    if team is None:
        return []
    return list(NotificationChannel.objects.filter(team=team, is_active=True))


def notify_status_change(monitor: "Monitor", old_status: str, new_status: str) -> None:
    """Fire notifications for this monitor's status change.

    Sends to the website's single channel (if its website has one set) AND any
    explicit per-monitor rules — deduped by channel so the same channel never
    gets two messages.
    """
    from apps.monitors.models import MonitorNotificationRule

    is_down = new_status == "down"
    is_recovery = old_status in ("down", "degraded") and new_status == "up"
    is_degraded = new_status == "degraded"

    if not (is_down or is_recovery or is_degraded):
        return

    channels = {}  # id -> channel, deduped

    # The website's own channel covers all status changes by default. A
    # dedicated uptime channel wins over the general website channel so
    # downtime alerts route separately from content/script alerts.
    if monitor.website_id:
        website = monitor.website
        uptime_ch = website.uptime_notification_channel
        if uptime_ch is not None and uptime_ch.is_active:
            channels[uptime_ch.id] = uptime_ch
        elif website.notification_channel_id:
            for ch in resolve_channels(website):
                # Only the website's explicitly-set channel auto-fires here; the
                # team-wide fallback is intentionally not used for uptime noise.
                if ch.is_active:
                    channels[ch.id] = ch

    # Explicit per-monitor rules (extra channels / fine-grained events).
    rules = MonitorNotificationRule.objects.filter(
        monitor=monitor, channel__is_active=True
    ).select_related("channel")
    for rule in rules:
        should_send = (
            (is_down and rule.notify_on_down)
            or (is_recovery and rule.notify_on_recovery)
            or (is_degraded and rule.notify_on_degraded)
        )
        if should_send:
            channels[rule.channel.id] = rule.channel

    for channel in channels.values():
        dispatch(channel, monitor, old_status, new_status)


# ------------------------------------------------------------------
# HTTP helper
# ------------------------------------------------------------------

def _http_post(url: str, payload: dict, *, name: str = "HTTP") -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status not in (200, 201, 202, 204):
            raise RuntimeError(f"{name} delivery returned HTTP {resp.status}")
