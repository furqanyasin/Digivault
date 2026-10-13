"""Which WordPress events are worth waking somebody for.

Most of the activity log is a record you consult after the fact. A small subset
is a thing you want to hear about now, and the difference is judgement rather
than severity: a new subscriber on a membership site is routine, a new
administrator on a brochure site is not.

Kept deliberately narrow. An alert stream that fires on every post edit trains
people to ignore it, and then the one that mattered gets ignored too.
"""
from __future__ import annotations

import logging

from django.utils import timezone
from django.utils.timezone import timedelta

from apps.site_health.models import SiteEvent

logger = logging.getLogger(__name__)

# WordPress roles ranked by what they can reach. A flat "privileged" set is not
# enough: editor -> administrator is a real escalation, and a set membership
# test reads both sides as privileged and stays silent on exactly the promotion
# worth hearing about.
_ROLE_RANK = {
    "subscriber": 1,
    "customer": 1,
    "contributor": 2,
    "author": 3,
    "shop_manager": 4,
    "editor": 4,
    "administrator": 5,
    "super admin": 6,
}

# At or above this rank, an account can change code or other users.
PRIVILEGED_RANK = _ROLE_RANK["editor"]


def _rank(role: str) -> int:
    """Rank for a role name, 0 for one we do not recognise.

    Unknown custom roles rank 0 deliberately: treating an unrecognised role as
    privileged would fire on every membership plugin's bespoke tier.
    """
    return _ROLE_RANK.get(role, 0)


LOGIN_FAILURE_BURST = 10
LOGIN_FAILURE_WINDOW_MINUTES = 15

_OUTSIDE_ADMIN_MARK = "changed outside wp-admin"


def _role(details: dict, key: str) -> str:
    return str((details or {}).get(key) or "").strip().lower()


def alertable_reason(event: SiteEvent) -> str | None:
    """The alert reason code for this event, or None if it is routine."""
    details = event.details or {}

    if event.event_type == SiteEvent.EventType.WP_USER_CREATED:
        if _rank(_role(details, "role")) >= PRIVILEGED_RANK:
            return "wp.admin_user_created"
        return None

    if event.event_type == SiteEvent.EventType.WP_USER_ROLE_CHANGED:
        # Only upward movement into privilege. A demotion is housekeeping;
        # being told about it at 3am costs attention and buys nothing.
        new_rank = _rank(_role(details, "new_role"))
        old_rank = _rank(_role(details, "old_role"))
        if new_rank >= PRIVILEGED_RANK and new_rank > old_rank:
            return "wp.role_escalated"
        return None

    if event.event_type == SiteEvent.EventType.WP_LOGIN_FAILED:
        window = timezone.now() - timedelta(minutes=LOGIN_FAILURE_WINDOW_MINUTES)
        recent = SiteEvent.objects.filter(
            website_id=event.website_id,
            event_type=SiteEvent.EventType.WP_LOGIN_FAILED,
            occurred_at__gte=window,
        ).count()
        return "wp.login_failed_burst" if recent >= LOGIN_FAILURE_BURST else None

    # Executable code appearing where only user content belongs. The file
    # walk marks these CRITICAL; nothing else in the file stream alerts, or a
    # routine plugin update would page someone every week.
    if (
        event.event_type == SiteEvent.EventType.WP_FILE_CHANGED
        and event.severity == SiteEvent.Severity.CRITICAL
    ):
        return "wp.core_file_changed"

    # The unattributed-component signal from wp_merge. Not a WP Connect event at
    # all — it is a passive row that no admin action ever explained.
    if _OUTSIDE_ADMIN_MARK in (event.summary or ""):
        return "wp.plugin_changed_outside_admin"

    return None


def dispatch_for_site_event(event: SiteEvent) -> list:
    """Create Notification records for an alertable site event.

    Mirrors `AlertService.dispatch_for_change`: per-website rules shadow global
    rules on the same channel. Severity gating is deliberately not applied — the
    reason codes above are already the filter, and a team whose min_severity is
    "high" should still hear that someone made themselves an administrator.
    """
    reason = alertable_reason(event)
    if reason is None:
        return []

    from apps.alerts.models import AlertRule, Notification

    website = event.website
    team = website.team

    website_rules = list(
        AlertRule.objects.filter(team=team, website=website, is_active=True)
    )
    global_rules = list(
        AlertRule.objects.filter(team=team, website__isnull=True, is_active=True)
    )
    covered = {r.channel for r in website_rules}
    rules = website_rules + [r for r in global_rules if r.channel not in covered]

    notifications = []
    for rule in rules:
        notifications.append(
            Notification.objects.create(
                team=team,
                website=website,
                site_event=event,
                rule=rule,
                channel=rule.channel,
            )
        )

    if notifications:
        logger.info(
            "wp_alerts: %s on %s -> %d notification(s)",
            reason, website.domain, len(notifications),
        )
    return notifications
