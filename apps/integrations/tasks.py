"""Reporting Stacks Monitor issues into ClickUp as tasks.

Give `report_issue` a stable subject and it either opens a task or adds a
comment to the one already open for that subject.

**Not wired into alert delivery.** Alerts post a message to the shared chat
channel and stop there (`apps/integrations/chat.py`) — the agency triages from
the channel and does not want a task per blip. This stays because a team's
`clickup_list_id` is still configurable in Settings and task filing is the
feature that setting exists for.
"""
from __future__ import annotations

import logging

from apps.integrations.clickup import ClickUpClient, ClickUpError
from apps.integrations.models import ClickUpTaskLink

logger = logging.getLogger(__name__)


def report_issue(
    team,
    subject: str,
    *,
    title: str,
    body: str = "",
    assignees: list | None = None,
    tags: list | None = None,
    client: ClickUpClient | None = None,
) -> ClickUpTaskLink | None:
    """Open (or update) the ClickUp task for `subject`.

    Returns the link, or None when the team has not configured ClickUp — an
    unconfigured team is the normal case, not an error, so this stays quiet
    rather than raising into the alert path.
    """
    list_id = getattr(team, "clickup_list_id", "") or ""
    token = getattr(team, "clickup_api_token", "") or ""
    if not list_id or not (token or client):
        return None

    api = client or ClickUpClient(token)

    existing = ClickUpTaskLink.objects.filter(
        team=team, subject=subject, closed_at__isnull=True
    ).first()

    try:
        if existing:
            api.comment(existing.task_id, body or title)
            return existing

        task = api.create_task(
            list_id, name=title, description=body, assignees=assignees, tags=tags
        )
    except ClickUpError:
        # Never let a ClickUp outage take down the alert that triggered it —
        # the email/chat channels have already delivered by this point.
        logger.exception("ClickUp report failed for subject %s", subject)
        return None

    task_id = str(task.get("id") or "")
    if not task_id:
        logger.warning("ClickUp created a task with no id for subject %s", subject)
        return None

    return ClickUpTaskLink.objects.create(
        team=team, subject=subject, task_id=task_id, task_url=task.get("url") or ""
    )
