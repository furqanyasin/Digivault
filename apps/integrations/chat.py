"""Announcing website problems in the team's ClickUp Chat channel.

One channel holds the whole web team; every problem posted there names the site,
the problem, and the developer who owns that client. `notify_problem` is the only
function alert paths need — it opens (or comments on) the ClickUp task for the
issue and posts the message that links to it.

Nothing here raises. By the time an alert path calls us, email and the
per-website channels have already delivered; a ClickUp outage must not undo that.
"""
from __future__ import annotations

import logging

from apps.integrations.clickup import ClickUpClient, parse_clickup_chat
from apps.integrations.members import clickup_id_for
from apps.integrations.models import ClickUpMemberLink, ClickUpTaskLink
from apps.integrations.tasks import report_issue

logger = logging.getLogger(__name__)

PROBLEM_EMOJI = "🔴"
RECOVERY_EMOJI = "✅"


def resolve_owner(website):
    """The developer accountable for this website.

    Ownership lives on the client, not the site — an agency assigns a person to
    an account. None when the site has no client or the client is unassigned.
    """
    client = getattr(website, "client", None)
    return getattr(client, "assigned_to", None) if client else None


def mention_for(team, user) -> tuple[str, str | None]:
    """(display_text, clickup_user_id) for a user.

    An unmapped user gets a bare name rather than "@name", so the message never
    renders an @-mention that resolves to nobody.
    """
    if user is None:
        return "unassigned", None

    clickup_id = clickup_id_for(team, user)
    label = (getattr(user, "get_full_name", lambda: "")() or "").strip() or user.email

    if clickup_id:
        link = ClickUpMemberLink.objects.filter(team=team, user=user).first()
        username = (link.clickup_username if link else "") or label
        return f"@{username}", clickup_id

    return label, None


def _chat_target(team) -> tuple[str | None, str | None]:
    return parse_clickup_chat(getattr(team, "clickup_chat_url", "") or "")


def _build_message(
    website, *, emoji: str, title: str, detail: str, mention: str, task_url: str
) -> str:
    label = website.name or website.domain
    lines = [
        f"{emoji} **{label}** — {title}",
        f"{website.domain} · owner: {mention}",
    ]
    if detail:
        lines.append(detail)
    if task_url:
        lines.append(f"→ {task_url}")
    return "\n".join(lines)


def _post(team, workspace_id, channel_id, text, followers, client) -> bool:
    api = client or ClickUpClient(team.clickup_api_token)
    api.post_chat(workspace_id, channel_id, text, followers=followers or None)
    return True


def notify_problem(
    website,
    *,
    subject: str,
    title: str,
    detail: str = "",
    tags: list | None = None,
    emoji: str = PROBLEM_EMOJI,
    client: ClickUpClient | None = None,
) -> bool:
    """Announce a website problem in the team channel and open its ClickUp task.

    `subject` is the stable issue key (e.g. "monitor:<id>:down") that dedupes
    repeat reports onto one task. Returns whether a message was posted.
    """
    team = website.team
    workspace_id, channel_id = _chat_target(team)
    if not (workspace_id and channel_id):
        return False

    try:
        owner = resolve_owner(website)
        mention, clickup_id = mention_for(team, owner)

        link = report_issue(
            team,
            subject,
            title=f"{website.name or website.domain}: {title}",
            body=detail or title,
            assignees=[clickup_id] if clickup_id else None,
            tags=tags,
            client=client,
        )

        text = _build_message(
            website, emoji=emoji, title=title, detail=detail,
            mention=mention, task_url=link.task_url if link else "",
        )
        return _post(
            team, workspace_id, channel_id, text, [clickup_id] if clickup_id else None, client
        )
    except Exception:
        logger.exception("ClickUp chat notify failed for %s (%s)", website.domain, subject)
        return False


def notify_recovery(
    website,
    *,
    subject: str,
    title: str,
    detail: str = "",
    client: ClickUpClient | None = None,
) -> bool:
    """Announce that a problem cleared, and close its open ClickUp task link.

    Closing matters: while a link is open, repeat reports comment on the old
    task. The next genuine occurrence should get a fresh one.
    """
    team = website.team
    workspace_id, channel_id = _chat_target(team)
    if not (workspace_id and channel_id):
        return False

    try:
        for link in ClickUpTaskLink.objects.filter(
            team=team, subject=subject, closed_at__isnull=True
        ):
            link.close()

        owner = resolve_owner(website)
        mention, clickup_id = mention_for(team, owner)
        text = _build_message(
            website, emoji=RECOVERY_EMOJI, title=title, detail=detail,
            mention=mention, task_url="",
        )
        return _post(
            team, workspace_id, channel_id, text, [clickup_id] if clickup_id else None, client
        )
    except Exception:
        logger.exception("ClickUp recovery notify failed for %s (%s)", website.domain, subject)
        return False
