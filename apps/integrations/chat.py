"""Announcing website problems in the team's ClickUp Chat channel.

One channel carries every client and every website, so a message only works if
it says — on its own — which client it belongs to, which site broke, what
exactly went wrong, and who manages it. That is what `build_message` renders
and what every alert path feeds.

Messages only. Alerts used to open a ClickUp task per issue; they no longer do.
`report_issue` (`apps/integrations/tasks.py`) still exists for callers that want
a task, but nothing in the alert path calls it.

The "@name" in a message is plain text and always will be: ClickUp's Chat API
exposes no request-side @-mention syntax, so nothing we put in `content` becomes
a real mention chip. Reaching a person is done with the message's `assignee`
(the account owner) and `followers` (everyone else who manages the site), which
is why the mapping between a Digivault user and their ClickUp id is resolved
here rather than left to whenever someone last opened Settings.

Nothing here raises. By the time an alert path calls us, email and the
per-website channels have already delivered; a ClickUp outage must not undo that.
"""
from __future__ import annotations

import logging

from apps.integrations.clickup import ClickUpClient, parse_clickup_chat
from apps.integrations.members import resolve_member_link

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


def resolve_managers(website) -> list:
    """Everyone who manages this website, most accountable first.

    The client's assignee owns the account; the site's `WebsiteAssignment` rows
    are the people actually working on it. Both get named and pinged — the
    account owner alone was not enough to reach whoever is on the site today.
    Deduped, because the same person is frequently both.
    """
    from apps.websites.models import WebsiteAssignment

    managers = []
    seen = set()

    for user in [resolve_owner(website)]:
        if user is not None and user.pk not in seen:
            seen.add(user.pk)
            managers.append(user)

    if getattr(website, "pk", None):
        assignments = (
            WebsiteAssignment.objects.filter(website=website)
            .select_related("user")
            .order_by("user__email")
        )
        for assignment in assignments:
            user = assignment.user
            if user is not None and user.pk not in seen:
                seen.add(user.pk)
                managers.append(user)

    return managers


def mention_for(team, user, *, client: ClickUpClient | None = None) -> tuple[str, str | None]:
    """(display_text, clickup_user_id) for a user.

    The mapping is resolved on demand: a manager the settings sync never matched
    used to render as a bare name and drop out of the ping entirely, which is
    exactly the case an alert cares about most.

    A user ClickUp genuinely does not know still gets a bare name rather than
    "@name", so the message never shows an @ that resolves to nobody.
    """
    if user is None:
        return "unassigned", None

    label = (getattr(user, "get_full_name", lambda: "")() or "").strip() or user.email
    link = resolve_member_link(team, user, client=client)

    if link and link.clickup_user_id:
        return f"@{link.clickup_username or label}", link.clickup_user_id

    return label, None


def mentions_for(team, users, *, client: ClickUpClient | None = None) -> tuple[str, list]:
    """(display_text, clickup_user_ids) for a group of managers.

    The text names everyone so a human reading the feed knows who to chase; the
    ids are what ClickUp actually notifies. An unmapped manager still appears in
    the text — being unlinked in ClickUp should not erase them from the message.

    Order is significant: the first id is the account owner, and `_announce`
    assigns the message to them.
    """
    if not users:
        return "unassigned", []

    labels, ids = [], []
    for user in users:
        label, clickup_id = mention_for(team, user, client=client)
        labels.append(label)
        if clickup_id:
            ids.append(clickup_id)
    return ", ".join(labels), ids


def chat_target(team) -> tuple[str | None, str | None]:
    return parse_clickup_chat(getattr(team, "clickup_chat_url", "") or "")


def _site_label(website) -> str:
    return website.name or website.domain


def _client_name(website) -> str:
    client = getattr(website, "client", None)
    return (getattr(client, "name", "") or "").strip() if client else ""


def _context_fields(website) -> list[tuple[str, str]]:
    """The who/where lines every message opens with, client first."""
    fields = []
    client_name = _client_name(website)
    if client_name:
        fields.append(("Client", client_name))
    label = _site_label(website)
    domain = website.domain or ""
    site = f"{label} ({domain})" if domain and domain != label else label
    fields.append(("Website", site))
    return fields


def build_message(
    website,
    *,
    emoji: str,
    title: str,
    detail: str = "",
    fields: list | None = None,
    mention: str = "",
) -> str:
    """Render one channel message.

    Public because the per-website ClickUp channels render the same message —
    a site routed to its own channel should not get a poorer alert than the
    shared feed.

    Shape is fixed so the shared feed scans consistently: a headline naming the
    client and the site, a block of labelled facts, then who is on the hook.
    Empty values are dropped rather than rendered as "Error: " with nothing
    after it.
    """
    client_name = _client_name(website)
    label = _site_label(website)
    headline = (
        f"{emoji} **{client_name}** — {label} {title}"
        if client_name
        else f"{emoji} **{label}** {title}"
    )

    lines = [headline, ""]

    for name, value in _context_fields(website) + list(fields or []):
        text = "" if value is None else str(value).strip()
        if text:
            lines.append(f"{name}: {text}")

    if detail:
        lines.append("")
        lines.append(detail)

    if mention:
        lines.append("")
        lines.append(f"Managed by: {mention}")

    return "\n".join(lines)


def _announce(
    website,
    *,
    emoji: str,
    title: str,
    detail: str,
    fields: list | None,
    client: ClickUpClient | None,
    log_context: str,
) -> bool:
    team = website.team
    workspace_id, channel_id = chat_target(team)
    if not (workspace_id and channel_id):
        return False

    # One client for the whole announcement: the member lookup and the post
    # share it, so a test's fake session sees both and production opens one
    # connection rather than two.
    api = client or ClickUpClient(team.clickup_api_token)

    try:
        mention, follower_ids = mentions_for(team, resolve_managers(website), client=api)
        text = build_message(
            website, emoji=emoji, title=title, detail=detail,
            fields=fields, mention=mention,
        )
        # ClickUp's Chat API has no inline @-mention syntax, so the "@name" in
        # the body is only readable text. Assignment is what actually reaches a
        # person; followers is what puts the rest of the managers on the thread.
        api.post_chat(
            workspace_id, channel_id, text,
            followers=follower_ids or None,
            assignee=follower_ids[0] if follower_ids else None,
        )
        return True
    except Exception:
        logger.exception("ClickUp chat notify failed for %s (%s)", website.domain, log_context)
        return False


def notify_problem(
    website,
    *,
    subject: str,
    title: str,
    detail: str = "",
    fields: list | None = None,
    emoji: str = PROBLEM_EMOJI,
    client: ClickUpClient | None = None,
) -> bool:
    """Announce a website problem in the shared channel.

    `fields` is an ordered list of `(label, value)` pairs rendered under the
    headline — the error text, HTTP status, timing and anything else the caller
    knows. `subject` is the issue key; it survives only as log context now that
    nothing opens a ClickUp task. Returns whether a message was posted.
    """
    return _announce(
        website, emoji=emoji, title=title, detail=detail, fields=fields,
        client=client, log_context=subject,
    )


def notify_recovery(
    website,
    *,
    subject: str,
    title: str,
    detail: str = "",
    fields: list | None = None,
    client: ClickUpClient | None = None,
) -> bool:
    """Announce that a problem cleared.

    Rendered identically to the problem message it clears — a recovery that does
    not name the same client, site and facts is unmatchable in a shared feed.
    """
    return _announce(
        website, emoji=RECOVERY_EMOJI, title=title, detail=detail, fields=fields,
        client=client, log_context=subject,
    )
