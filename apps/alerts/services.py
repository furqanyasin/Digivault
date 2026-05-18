"""Alert rule matching and notification creation.

Called by the script processing Celery task after the diff engine
produces a list of ScriptChange records.
"""

from __future__ import annotations

import logging

from apps.alerts.models import AlertRule, Notification
from apps.scripts.models import ScriptChange

logger = logging.getLogger(__name__)

_SEVERITY_LEVELS = {"high": 3, "medium": 2, "low": 1}


class AlertService:
    """Match a ScriptChange against active alert rules and create Notification records."""

    @classmethod
    def dispatch_for_change(cls, change: ScriptChange) -> list[Notification]:
        """Create Notification records for every matching rule.

        The actual delivery (email send, Slack POST) is queued as a separate
        Celery task per notification so failures are isolated and retryable.
        """
        website = change.website
        team = website.team

        # Collect applicable rules: per-website overrides + global fallback
        website_rules = list(
            AlertRule.objects.filter(
                team=team, website=website, is_active=True
            )
        )
        global_rules = list(
            AlertRule.objects.filter(
                team=team, website__isnull=True, is_active=True
            )
        )

        # Per-website rules shadow global rules for the same channel
        covered_channels = {r.channel for r in website_rules}
        applicable_rules = website_rules + [
            r for r in global_rules if r.channel not in covered_channels
        ]

        notifications = []
        for rule in applicable_rules:
            if cls._rule_matches(rule, change):
                notif = Notification.objects.create(
                    team=team,
                    website=website,
                    script_change=change,
                    rule=rule,
                    channel=rule.channel,
                )
                notifications.append(notif)

        return notifications

    @staticmethod
    def _rule_matches(rule: AlertRule, change: ScriptChange) -> bool:
        # Severity gate
        required = _SEVERITY_LEVELS.get(rule.min_severity, 1)
        actual = _SEVERITY_LEVELS.get(change.severity, 0)
        if actual < required:
            return False
        # Change-type filter (empty list = all types)
        if rule.change_types and change.change_type not in rule.change_types:
            return False
        return True
