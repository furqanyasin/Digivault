"""Outbound notification delivery for uptime monitor status changes.

Each dispatcher is a small stateless function that accepts a monitor,
the old status, the new status, and the NotificationChannel record.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import TYPE_CHECKING

from django.utils import timezone

# parse_clickup_chat is re-exported: it used to live here, and tests plus other
# callers still import it from this module.
from apps.integrations.clickup import ClickUpClient, parse_clickup_chat  # noqa: F401

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
# What actually happened
# ------------------------------------------------------------------

def latest_check(monitor):
    """The check that caused this status change.

    Every caller of `notify_status_change` writes its MonitorCheck immediately
    before notifying, so the newest row is the one being reported. Read here
    rather than threaded through the signature so both call sites — the Celery
    task and the manual "Run check" view — get the detail for free.
    """
    from apps.monitors.models import MonitorCheck

    return MonitorCheck.objects.filter(monitor=monitor).order_by("-checked_at").first()


def _format_time(value) -> str:
    if not value:
        return ""
    return timezone.localtime(value).strftime("%d %b %Y, %H:%M %Z").strip()


def status_fields(monitor, old_status: str, new_status: str, check=None) -> list:
    """Labelled facts describing a status change, for the channel message.

    "Down" with no reason is the complaint this answers — the error text, the
    HTTP code and the timing all come off the check row and get named, so
    whoever reads the alert knows what to look at before opening the dashboard.
    """
    fields = [
        ("URL", monitor.url),
        ("Status", f"{old_status.upper()} → {new_status.upper()}"),
    ]

    if check is not None:
        if check.error_message:
            fields.append(("Error", check.error_message))
        if check.status_code:
            fields.append(("HTTP status", check.status_code))
        if check.response_time_ms is not None:
            fields.append(("Response time", f"{check.response_time_ms} ms"))
        fields.append(("Checked at", _format_time(check.checked_at)))
    else:
        fields.append(("Checked at", _format_time(monitor.last_checked_at)))

    if new_status != "up" and monitor.consecutive_failures:
        fields.append(("Failed checks", f"{monitor.consecutive_failures} in a row"))

    fields.append(("Monitor", f"{monitor.name} ({monitor.get_monitor_type_display()})"))
    return fields


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
    subject = f"[Stacks Monitor] {monitor.name} is {new_status.upper()}"
    detail = "\n".join(
        f"{label}: {value}"
        for label, value in status_fields(monitor, old_status, new_status, latest_check(monitor))
        if str(value or "").strip()
    )
    body = f"{detail}\n\nLog in to Stacks Monitor to view details."
    from_email = settings.DEFAULT_FROM_EMAIL
    try:
        send_mail(subject, body, from_email, addresses, fail_silently=False)
    except Exception:
        logger.exception("Email delivery failed for channel %s", channel.id)
        raise


def post_clickup(config: dict, text: str, followers: list | None = None) -> bool:
    """Post `text` to a ClickUp target. Prefers a Chat channel (v3 API) when the
    config has a `chat_url`; otherwise comments on a `task_id` (v2). Returns True
    if a request was sent, False if the config has no usable target. Raises
    ClickUpError on a non-2xx response so callers can log/retry.

    `followers` only applies to chat: it is what actually pings a person, since
    v3 has no request-side @-mention syntax. Task comments ignore it."""
    config = config or {}
    api_token = config.get("api_token", "")
    if not api_token:
        return False

    api = ClickUpClient(api_token)

    chat_url = config.get("chat_url", "")
    if chat_url:
        ws, ch = parse_clickup_chat(chat_url)
        if ws and ch:
            api.post_chat(ws, ch, text, followers=followers or None)
            return True

    task_id = config.get("task_id", "")
    if task_id:
        api.comment(task_id, text)
        return True

    return False


def _send_clickup(channel, monitor, old_status: str, new_status: str) -> None:
    """Post the status change to a website's own ClickUp channel.

    Rendered by the same builder as the shared feed: a site with a dedicated
    channel must not get a thinner message than one without.
    """
    from apps.integrations import chat

    website = monitor.website
    if website is None:
        # No website means no client, no managers and no context to render —
        # fall back to the flat monitor line.
        text = (
            f"{STATUS_EMOJI.get(new_status, '')} **{monitor.name}** status changed: "
            f"{old_status.upper()} → {new_status.upper()}\nURL: {monitor.url}"
        )
        followers = None
    else:
        mention, followers = chat.mentions_for(
            website.team, chat.resolve_managers(website)
        )
        text = chat.build_message(
            website,
            emoji=STATUS_EMOJI.get(new_status, ""),
            title=_status_title(old_status, new_status),
            fields=status_fields(monitor, old_status, new_status, latest_check(monitor)),
            mention=mention,
        )

    if not post_clickup(channel.config, text, followers):
        logger.warning("ClickUp channel %s has no api_token or target", channel.id)


def _status_title(old_status: str, new_status: str) -> str:
    if new_status == "up":
        return "is back UP"
    return f"is {new_status.upper()}"


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

    # The shared team channel is announced separately from the per-website
    # channels above: a team gets it whether or not any website channel is set.
    if monitor.website_id:
        _announce_in_team_channel(
            monitor, old_status, new_status, is_recovery,
            already_posted=_chat_targets(channels.values()),
        )


def _chat_targets(channels) -> set:
    """The ClickUp chat (workspace, channel) pairs these channels post to.

    Everything routes to one shared ClickUp channel, so a website whose own
    channel points at that same chat would otherwise get the identical alert
    twice — once from `dispatch`, once from the team announce.
    """
    targets = set()
    for channel in channels:
        if channel.channel_type != "clickup":
            continue
        ws, ch = parse_clickup_chat((channel.config or {}).get("chat_url", ""))
        if ws and ch:
            targets.add((ws, ch))
    return targets


def _announce_in_team_channel(
    monitor, old_status: str, new_status: str, is_recovery: bool,
    already_posted: set | None = None,
) -> None:
    """Post the status change into the team's ClickUp channel.

    Deliberately best-effort and separate from `dispatch` — this is one shared
    feed for the whole web team, not a configured channel row.
    """
    from apps.integrations import chat

    website = monitor.website
    if already_posted and chat.chat_target(website.team) in already_posted:
        return

    subject = f"monitor:{monitor.id}:down"
    fields = status_fields(monitor, old_status, new_status, latest_check(monitor))
    title = _status_title(old_status, new_status)

    if is_recovery:
        chat.notify_recovery(website, subject=subject, title=title, fields=fields)
        return

    chat.notify_problem(website, subject=subject, title=title, fields=fields)


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
