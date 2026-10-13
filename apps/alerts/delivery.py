"""Alert delivery backends.

Each backend is a small stateless class with a single `send(notification)` method.
The Celery task selects the right backend based on `notification.channel`.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


class EmailDelivery:
    @staticmethod
    def send(notification) -> None:
        change = notification.script_change
        event = notification.site_event
        if change:
            subject = (
                f"[Digivault] {notification.website.name}: "
                f"{change.severity.upper()} alert"
            )
        elif event:
            subject = f"[Digivault] {notification.website.name}: {event.summary}"
        else:
            subject = f"[Digivault] {notification.website.name}: alert"
        body = _build_email_body(notification)
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "alerts@digivault.digilatics.co")
        recipients = _team_email_recipients(notification.team)
        if not recipients:
            logger.warning("EmailDelivery: no recipients for team %s", notification.team_id)
            return
        send_mail(subject, body, from_email, recipients, fail_silently=False)


# Hosts a Slack webhook may live on. `slack_webhook_url` is a URLField any team
# member can write — there is no role gate on creating an alert rule — and it
# used to be handed straight to `urllib.request.urlopen` with the default
# opener. That is a server-side request to an attacker-chosen address with
# unguarded redirects: cloud metadata at 169.254.169.254, Redis, or this very
# API on 127.0.0.1:8000 were all one alert away.
#
# The allowlist is the real fix — an SSRF sink with a fixed destination is not a
# sink. Routing through `outbound.fetch` on top of it is defence in depth: it
# re-applies the SSRF guard on every redirect hop, so a `hooks.slack.com` that
# someone has persuaded to 302 elsewhere still goes nowhere.
SLACK_WEBHOOK_HOSTS = frozenset({"hooks.slack.com"})


class SlackDelivery:
    @staticmethod
    def send(notification) -> None:
        import json as _json
        from urllib.parse import urlsplit

        from apps.common import outbound

        rule = notification.rule
        if not rule or not rule.slack_webhook_url:
            logger.warning("SlackDelivery: no webhook URL for notification %s", notification.pk)
            return

        host = (urlsplit(rule.slack_webhook_url).hostname or "").lower()
        if host not in SLACK_WEBHOOK_HOSTS:
            # Refused, not attempted. Raising would retry the same rejected URL
            # on a schedule; this is a configuration error, and the log names it.
            logger.error(
                "SlackDelivery: refusing webhook on non-Slack host %r (rule %s) — "
                "only %s is accepted",
                host, rule.pk, ", ".join(sorted(SLACK_WEBHOOK_HOSTS)),
            )
            return

        payload = _build_slack_payload(notification)
        result = outbound.fetch(
            rule.slack_webhook_url,
            method="POST",
            timeout=10,
            data=_json.dumps(payload).encode("utf-8"),
            extra_headers={"Content-Type": "application/json"},
            # Slack is a third-party API, not a customer origin: the per-host
            # budget exists to keep us off client WAF blocklists and pacing
            # alert delivery at one per 20 seconds would be actively wrong.
            bypass_budget=True,
        )
        if result.status_code != 200:
            raise RuntimeError(f"Slack webhook returned {result.status_code}")


class ClickUpDelivery:
    """Post the alert as a comment on the team's active ClickUp notification
    channel(s). Reuses the NotificationChannel config (api_token + task_id) that
    powers uptime/website alerts, so no extra config lives on the rule."""

    @staticmethod
    def send(notification) -> None:
        from apps.monitors.models import NotificationChannel
        from apps.monitors.notifications import post_clickup

        channels = list(
            NotificationChannel.objects.filter(
                team=notification.team, is_active=True, channel_type="clickup"
            )
        )
        if not channels:
            logger.warning(
                "ClickUpDelivery: no active ClickUp channel for team %s", notification.team_id
            )
            return

        comment = _build_clickup_comment(notification)
        # post_clickup routes to a Chat channel (v3) or a task comment (v2)
        # depending on the channel config.
        delivered = any(post_clickup(ch.config, comment) for ch in channels)
        if not delivered:
            logger.warning(
                "ClickUpDelivery: ClickUp channel(s) for team %s have no usable target",
                notification.team_id,
            )


class InAppDelivery:
    """In-app delivery creates the Notification record and pushes it to any
    open WebSocket connections for the team via the Channels layer."""

    @staticmethod
    def send(notification) -> None:
        from apps.alerts.consumers import push_notification

        push_notification(notification)


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

_BACKENDS = {
    "email": EmailDelivery,
    "clickup": ClickUpDelivery,
    "slack": SlackDelivery,
    "in_app": InAppDelivery,
}


def get_backend(channel: str):
    backend = _BACKENDS.get(channel)
    if backend is None:
        raise ValueError(f"No delivery backend for channel '{channel}'")
    return backend


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _team_email_recipients(team) -> list[str]:
    return list(
        team.memberships.filter(
            role__in=["owner", "manager"]
        ).values_list("user__email", flat=True)
    )


def _build_email_body(notification) -> str:
    change = notification.script_change
    lines = [
        f"Website: {notification.website.name} ({notification.website.domain})",
    ]
    if change:
        lines += [
            f"Change type: {change.get_change_type_display()}",
            f"Severity: {change.severity.upper()}",
            f"Description: {change.description}",
        ]
        if change.old_value:
            lines.append(f"Before: {change.old_value}")
        if change.new_value:
            lines.append(f"After: {change.new_value}")
    lines += _site_event_lines(notification)
    lines.append("\nView in Digivault dashboard to acknowledge this alert.")
    return "\n".join(lines)


def _site_event_lines(notification) -> list[str]:
    """Describe a WordPress activity event.

    Who, and from where, is the whole point of the attributed log — an alert
    saying only "something changed on acme.test" is the alert people learn to
    ignore.
    """
    event = getattr(notification, "site_event", None)
    if event is None:
        return []
    lines = [
        f"Event: {event.get_event_type_display()}",
        f"Severity: {event.severity.upper()}",
        f"What: {event.summary}",
    ]
    if event.actor:
        lines.append(f"Who: {event.actor}")
    if event.actor_ip:
        lines.append(f"From: {event.actor_ip}")
    lines.append(f"When: {event.occurred_at:%Y-%m-%d %H:%M UTC}")
    return lines


def _build_clickup_comment(notification) -> str:
    change = notification.script_change
    lines = [f"🔔 {notification.website.name} ({notification.website.domain})"]
    if change:
        lines.append(f"{change.get_change_type_display()} — {change.severity.upper()}")
        if change.description:
            lines.append(change.description)
    lines += _site_event_lines(notification)
    return "\n".join(lines)


def _build_slack_payload(notification) -> dict:
    change = notification.script_change
    severity_colors = {"high": "#ef4444", "medium": "#f59e0b", "low": "#94a3b8"}
    color = severity_colors.get(getattr(change, "severity", "low"), "#94a3b8")

    text = f"*{notification.website.name}* — {notification.website.domain}"
    if change:
        text += f"\n*{change.get_change_type_display()}* — {change.description}"
    event = getattr(notification, "site_event", None)
    if event is not None:
        text += f"\n*{event.get_event_type_display()}* — {event.summary}"
        if event.actor:
            text += f" (by {event.actor}"
            text += f" from {event.actor_ip})" if event.actor_ip else ")"

    return {
        "attachments": [
            {
                "color": color,
                "text": text,
                "footer": "Digivault",
            }
        ]
    }
