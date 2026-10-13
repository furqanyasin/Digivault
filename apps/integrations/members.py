"""Matching Stacks Monitor users to ClickUp workspace members.

ClickUp gives us one reliable join key — email — and agency staff often have a
different address in each system. So matching produces both a matched and an
unmatched list; the unmatched list is what the settings UI asks a human to fix,
and `set_member_link` is how they fix it.

Two ways in. `sync_member_links` is the deliberate, whole-team pass a manager
runs from Settings. `resolve_member_link` is the lazy one an alert takes when it
needs a single person right now: settings syncs are rare and email matching is
brittle, so relying on them alone meant alerts named managers as bare text and
pinged nobody. Falling back to name matching costs nothing here — the worst case
is the same "unmatched" the settings UI already handles.
"""
from __future__ import annotations

import logging
import re

from django.core.cache import cache

from apps.integrations.clickup import ClickUpClient, ClickUpError
from apps.integrations.models import ClickUpMemberLink

logger = logging.getLogger(__name__)

EMPTY_SYNC = {"matched": [], "unmatched": [], "workspace_id": None}

# A live outage re-fires every 30s and each alert may touch several managers.
# The roster changes on the scale of hiring, so one fetch per team per ten
# minutes is plenty and keeps ClickUp out of the alert's critical path.
_ROSTER_CACHE_TTL = 600


def _team_members(team):
    """Every user in the team, with their membership loaded."""
    from apps.accounts.models import TeamMembership

    return [m.user for m in TeamMembership.objects.filter(team=team).select_related("user")]


def _norm_name(value: str) -> str:
    """A name reduced to comparable form: lowercase, alphanumerics only.

    "Junaid Naseem", "junaid.naseem" and "Junaid  Naseem" all collapse together,
    which is the shape the same person's name takes across the two systems.
    """
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _index_members(workspace: dict) -> dict:
    """Workspace members keyed by the two things we can match on.

    `by_email` wins whenever it hits. `by_name` holds ClickUp handles only —
    deliberately not their email local part, or two different people at
    `info@agency.com` and `info@client.com` would match each other. It also
    drops any handle that appears twice: an ambiguous name must resolve to
    nobody rather than to a coin flip that pings the wrong person.
    """
    by_email: dict[str, dict] = {}
    name_hits: dict[str, list] = {}

    for entry in workspace.get("members") or []:
        cu = entry.get("user") or {}
        if not cu.get("id"):
            continue
        email = (cu.get("email") or "").strip().lower()
        if email:
            by_email[email] = cu
        key = _norm_name(cu.get("username"))
        if key:
            name_hits.setdefault(key, []).append(cu)

    by_name = {k: v[0] for k, v in name_hits.items() if len(v) == 1}
    return {"by_email": by_email, "by_name": by_name}


def _roster(team, *, client: ClickUpClient | None = None) -> dict:
    """This team's ClickUp workspace roster, cached.

    Returns an empty index — never raises — when the team is unconfigured or
    ClickUp is unreachable. Callers are alert paths that must keep going.
    """
    key = f"clickup:roster:{team.pk}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    token = getattr(team, "clickup_api_token", "") or ""
    if not (token or client):
        return {"by_email": {}, "by_name": {}}

    api = client or ClickUpClient(token)
    try:
        workspaces = api.workspaces()
    except ClickUpError:
        logger.warning("ClickUp roster lookup failed for team %s", team.pk)
        # Not cached: a transient outage should not blind us for ten minutes.
        return {"by_email": {}, "by_name": {}}

    index = _index_members(workspaces[0] if workspaces else {})
    cache.set(key, index, _ROSTER_CACHE_TTL)
    return index


def _find_in_roster(roster: dict, user) -> dict | None:
    email = (getattr(user, "email", "") or "").strip().lower()
    cu = roster["by_email"].get(email)
    if cu:
        return cu

    full_name = (getattr(user, "get_full_name", lambda: "")() or "").strip()
    for candidate in (full_name, email.split("@")[0] if email else ""):
        key = _norm_name(candidate)
        if key and key in roster["by_name"]:
            return roster["by_name"][key]
    return None


def resolve_member_link(team, user, *, client: ClickUpClient | None = None):
    """This user's ClickUp mapping, looked up and stored the first time it is needed.

    Returns the stored `ClickUpMemberLink` when one exists, otherwise consults
    the workspace roster and persists what it finds. None when ClickUp does not
    know this person — which is a normal answer, not an error.
    """
    if user is None:
        return None

    link = ClickUpMemberLink.objects.filter(team=team, user=user).first()
    if link and link.clickup_user_id:
        return link

    cu = _find_in_roster(_roster(team, client=client), user)
    if not cu:
        return None
    return set_member_link(team, user, str(cu.get("id") or ""), cu.get("username") or "")


def sync_member_links(team, *, client: ClickUpClient | None = None) -> dict:
    """Match this team's users against ClickUp workspace members.

    Email first, then the ClickUp handle — see `_index_members` for why the
    fallback is deliberately narrow.

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
    roster = _index_members(workspace)
    # A fresh roster just arrived — hand it to the alert path too rather than
    # letting it re-fetch behind a stale entry.
    cache.set(f"clickup:roster:{team.pk}", roster, _ROSTER_CACHE_TTL)

    matched, unmatched = [], []
    for user in _team_members(team):
        cu = _find_in_roster(roster, user)
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


def username_for_clickup_id(team, clickup_user_id: str, *, client: ClickUpClient | None = None) -> str:
    """The ClickUp handle behind an id, or "" when unknown.

    A manual override arrives as an id alone. Storing it without the handle left
    `mention_for` rendering the person's Stacks Monitor full name after an "@" —
    "@Muhammad Furqan", a string ClickUp cannot resolve.
    """
    wanted = str(clickup_user_id or "").strip()
    if not wanted:
        return ""
    roster = _roster(team, client=client)
    for cu in roster["by_email"].values():
        if str(cu.get("id") or "") == wanted:
            return cu.get("username") or ""
    return ""
