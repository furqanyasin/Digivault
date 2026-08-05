"""Matching Digivault users to ClickUp workspace members.

ClickUp gives us one usable join key — email — and agency staff often have a
different address in each system. So matching produces both a matched and an
unmatched list; the unmatched list is what the settings UI asks a human to fix,
and `set_member_link` is how they fix it.
"""
from __future__ import annotations

import logging

from apps.integrations.clickup import ClickUpClient, ClickUpError
from apps.integrations.models import ClickUpMemberLink

logger = logging.getLogger(__name__)

EMPTY_SYNC = {"matched": [], "unmatched": [], "workspace_id": None}


def _team_members(team):
    """Every user in the team, with their membership loaded."""
    from apps.accounts.models import TeamMembership

    return [m.user for m in TeamMembership.objects.filter(team=team).select_related("user")]


def sync_member_links(team, *, client: ClickUpClient | None = None) -> dict:
    """Match this team's users against ClickUp workspace members by email.

    Returns {"matched": [...], "unmatched": [...], "workspace_id": str | None}.
    An unconfigured team returns EMPTY_SYNC rather than raising — that is the
    normal state, not a failure.
    """
    token = getattr(team, "clickup_api_token", "") or ""
    if not (token or client):
        return dict(EMPTY_SYNC)

    api = client or ClickUpClient(token)
    try:
        workspaces = api.workspaces()
    except ClickUpError:
        logger.exception("ClickUp workspace lookup failed for team %s", team.pk)
        return dict(EMPTY_SYNC)

    if not workspaces:
        return dict(EMPTY_SYNC)

    # The token belongs to one person; their first workspace is the team's.
    workspace = workspaces[0]
    by_email = {}
    for entry in workspace.get("members") or []:
        cu = entry.get("user") or {}
        email = (cu.get("email") or "").strip().lower()
        if email:
            by_email[email] = cu

    matched, unmatched = [], []
    for user in _team_members(team):
        cu = by_email.get((user.email or "").strip().lower())
        if not cu:
            unmatched.append({"user_id": str(user.id), "email": user.email})
            continue
        link = set_member_link(team, user, str(cu.get("id") or ""), cu.get("username") or "")
        matched.append({
            "user_id": str(user.id),
            "email": user.email,
            "clickup_user_id": link.clickup_user_id,
            "clickup_username": link.clickup_username,
        })

    return {
        "matched": matched,
        "unmatched": unmatched,
        "workspace_id": str(workspace.get("id") or "") or None,
    }


def set_member_link(
    team, user, clickup_user_id: str, clickup_username: str = ""
) -> ClickUpMemberLink:
    """Create or update one user's ClickUp mapping."""
    link, _ = ClickUpMemberLink.objects.update_or_create(
        team=team,
        user=user,
        defaults={
            "clickup_user_id": str(clickup_user_id or ""),
            "clickup_username": clickup_username or "",
        },
    )
    return link


def clickup_id_for(team, user) -> str | None:
    """This user's ClickUp id, or None when unmapped."""
    if user is None:
        return None
    link = ClickUpMemberLink.objects.filter(team=team, user=user).first()
    return link.clickup_user_id if link and link.clickup_user_id else None
