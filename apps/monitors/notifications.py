"""Outbound notification delivery for uptime monitor status changes.

Each dispatcher is a small stateless function that accepts a monitor,
the old status, the new status, and the NotificationChannel record.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import TYPE_CHECKING

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

def _send_slack(channel, monitor, old_status: str, new_status: str) -> None:
    url = channel.config.get("url", "")
    if not url:
        logger.warning("Slack channel %s missing url", channel.id)
        return
    color = "#22c55e" if new_status == "up" else "#ef4444" if new_status == "down" else "#f59e0b"
    payload = {
        "attachments": [{"color": color, "text": _summary(monitor, old_status, new_status), "footer": "Digivault Monitors"}]
    }
    _http_post(url, payload, name="Slack")


def _send_discord(channel, monitor, old_status: str, new_status: str) -> None:
    url = channel.config.get("url", "")
    if not url:
        logger.warning("Discord channel %s missing url", channel.id)
        return
    color = 0x22C55E if new_status == "up" else 0xEF4444 if new_status == "down" else 0xF59E0B
    payload = {
        "embeds": [
            {
                "title": f"{monitor.name} — {new_status.upper()}",
                "description": f"`{monitor.url}`\nPrevious status: **{old_status}**",
                "color": color,
                "footer": {"text": "Digivault Monitors"},
            }
        ]
    }
    _http_post(url, payload, name="Discord")


def _send_webhook(channel, monitor, old_status: str, new_status: str) -> None:
    url = channel.config.get("url", "")
    if not url:
        logger.warning("Webhook channel %s missing url", channel.id)
        return
    payload = {
        "monitor_id": str(monitor.id),
        "monitor_name": monitor.name,
        "url": monitor.url,
        "old_status": old_status,
        "new_status": new_status,
    }
    _http_post(url, payload, name="Webhook")


def _send_telegram(channel, monitor, old_status: str, new_status: str) -> None:
    bot_token = channel.config.get("bot_token", "")
    chat_id = channel.config.get("chat_id", "")
    if not bot_token or not chat_id:
        logger.warning("Telegram channel %s missing bot_token or chat_id", channel.id)
        return
    text = _summary(monitor, old_status, new_status)
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    _http_post(api_url, payload, name="Telegram")


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


# ------------------------------------------------------------------
# Dispatcher registry
# ------------------------------------------------------------------

_SENDERS = {
    "slack": _send_slack,
    "discord": _send_discord,
    "webhook": _send_webhook,
    "telegram": _send_telegram,
    "email": _send_email,
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


def notify_status_change(monitor: "Monitor", old_status: str, new_status: str) -> None:
    """Fire notifications for all rules linked to this monitor matching the event."""
    from apps.monitors.models import MonitorNotificationRule

    is_down = new_status == "down"
    is_recovery = old_status in ("down", "degraded") and new_status == "up"
    is_degraded = new_status == "degraded"

    if not (is_down or is_recovery or is_degraded):
        return

    rules = MonitorNotificationRule.objects.filter(
        monitor=monitor,
        channel__is_active=True,
    ).select_related("channel")

    for rule in rules:
        should_send = (
            (is_down and rule.notify_on_down)
            or (is_recovery and rule.notify_on_recovery)
            or (is_degraded and rule.notify_on_degraded)
        )
        if should_send:
            dispatch(rule.channel, monitor, old_status, new_status)


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
