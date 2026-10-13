"""Alert rule matching and notification creation.

Called by the script processing Celery task after the diff engine
produces a list of ScriptChange records.
"""

from __future__ import annotations

import logging

from apps.alerts.models import AlertRule, AlertSuppression, Notification
from apps.common.severity import meets as severity_meets
from apps.scripts.models import ScriptChange

logger = logging.getLogger(__name__)


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

        # Suppression gate — a muted provider/domain produces no notifications
        if change.script_id and cls._is_suppressed(change):
            return []

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
    def _is_suppressed(change: ScriptChange) -> bool:
        suppressions = AlertSuppression.objects.filter(website_id=change.website_id)
        return any(s.matches(change) for s in suppressions)

    @staticmethod
    def _rule_matches(rule: AlertRule, change: ScriptChange) -> bool:
        # Severity gate. Ranked by apps.common.severity so the model's
        # vocabulary and the rule's minimum cannot drift apart again: the local
        # rank map this replaced had no entry for `critical`, which scored it
        # below every rule minimum and made the highest severity the only one
        # that could never be delivered.
        if not severity_meets(change.severity, rule.min_severity):
            return False
        # Change-type filter (empty list = all types)
        if rule.change_types and change.change_type not in rule.change_types:
            return False
        return True
