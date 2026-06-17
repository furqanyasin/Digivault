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
        subject = (
            f"[Digivault] {notification.website.name}: "
            f"{change.severity.upper()} alert"
            if change
            else f"[Digivault] {notification.website.name}: alert"
        )
        body = _build_email_body(notification)
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "alerts@digivault.digilatics.co")
        recipients = _team_email_recipients(notification.team)
        if not recipients:
            logger.warning("EmailDelivery: no recipients for team %s", notification.team_id)
            return
        send_mail(subject, body, from_email, recipients, fail_silently=False)


class SlackDelivery:
    @staticmethod
    def send(notification) -> None:
        import urllib.request, json as _json

        rule = notification.rule
        if not rule or not rule.slack_webhook_url:
            logger.warning("SlackDelivery: no webhook URL for notification %s", notification.pk)
            return

        payload = _build_slack_payload(notification)
        data = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            rule.slack_webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Slack webhook returned {resp.status}")


class ClickUpDelivery:
    """Post the alert as a comment on the team's active ClickUp notification
    channel(s). Reuses the NotificationChannel config (api_token + task_id) that
    powers uptime/website alerts, so no extra config lives on the rule."""

    @staticmethod
    def send(notification) -> None:
        import json as _json
        import urllib.request

        from apps.monitors.models import NotificationChannel

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
        delivered = False
        for ch in channels:
            api_token = (ch.config or {}).get("api_token", "")
            task_id = (ch.config or {}).get("task_id", "")
            if not api_token or not task_id:
                continue
            url = f"https://api.clickup.com/api/v2/task/{task_id}/comment"
            data = _json.dumps({"comment_text": comment}).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json", "Authorization": api_token},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status not in (200, 201):
                    raise RuntimeError(f"ClickUp delivery returned HTTP {resp.status}")
            delivered = True
        if not delivered:
            logger.warning(
                "ClickUpDelivery: ClickUp channel(s) for team %s missing api_token/task_id",
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
    lines.append("\nView in Digivault dashboard to acknowledge this alert.")
    return "\n".join(lines)


def _build_clickup_comment(notification) -> str:
    change = notification.script_change
    lines = [f"🔔 {notification.website.name} ({notification.website.domain})"]
    if change:
        lines.append(f"{change.get_change_type_display()} — {change.severity.upper()}")
        if change.description:
            lines.append(change.description)
    return "\n".join(lines)


def _build_slack_payload(notification) -> dict:
    change = notification.script_change
    severity_colors = {"high": "#ef4444", "medium": "#f59e0b", "low": "#94a3b8"}
    color = severity_colors.get(getattr(change, "severity", "low"), "#94a3b8")

    text = f"*{notification.website.name}* — {notification.website.domain}"
    if change:
        text += f"\n*{change.get_change_type_display()}* — {change.description}"

    return {
        "attachments": [
            {
                "color": color,
                "text": text,
                "footer": "Digivault",
            }
        ]
    }
