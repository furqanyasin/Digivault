# ClickUp web team channel — design

**Date:** 2026-08-05
**Status:** approved, ready for planning

## Problem

When a client website has a problem, nobody on the web team is told in a place
they are already looking. Today's notification channels are per-website and
per-event: a `NotificationChannel` row carries a ClickUp task id or chat link in
its `config` blob, and each alert type (uptime, domain, SEO) hand-rolls its own
ClickUp call. There is no single team-facing feed, and no notion of *who* should
act — the message names the site but not the developer responsible for it.

Separately, the ClickUp integration settings card tells users "Digivault opens a
task here when a website has a problem." That is not true. `report_issue()` in
[apps/integrations/tasks.py](../../../apps/integrations/tasks.py) is complete,
tested, and called from nowhere but its own tests.

## Goal

One ClickUp Chat channel containing the whole web team. When a website has a
problem, Digivault posts a message there naming the website and the problem,
addressed to the developer who owns that client, and linking to the ClickUp task
it opened for the issue.

## What already exists

Deliberately reusing, not rebuilding:

- `ClickUpClient.post_chat(workspace_id, channel_id, text)` —
  [apps/integrations/clickup.py:105](../../../apps/integrations/clickup.py#L105),
  already speaks the v3 Chat API.
- `parse_clickup_chat(url) -> (workspace_id, channel_id)` —
  [apps/monitors/notifications.py:67](../../../apps/monitors/notifications.py#L67).
- `report_issue(team, subject, ...)` — dedupes issue → task via the
  `ClickUpTaskLink` table, swallows `ClickUpError`, no-ops for unconfigured teams.
- `Client.assigned_to` (FK to `User`) —
  [apps/clients/models.py:90](../../../apps/clients/models.py#L90). `Website.client`
  links to it, so the owning developer is already derivable.
- `Team.clickup_api_token` (Fernet-encrypted) and `Team.clickup_list_id`.

## Constraint discovered in the ClickUp API

`POST /v3/workspaces/{id}/chat/channels` accepts `name`, `description`,
`visibility`, and `user_ids` (up to 100) — so creating the channel with the whole
team in one call is supported.

**How to encode an @-mention inside a chat message body is undocumented.**
`createChatMessage` documents `type`, `content`, `content_format`
(`text/md` | `text/plain`), `assignee`, `followers` (up to 10), and `reactions`.
Responses expose a `tagged_users` link, but no request-side syntax is specified.

This design therefore does **not** depend on inline mention syntax. The actual
notification comes from the message's `followers` field, which is documented; the
body carries a plain `@username` for human readability. If a working mention
token is found later, it changes one function (`mention_for`) and nothing else.

## Components

### 1. `Team.clickup_chat_url` — where the channel lives

New field on `Team`, alongside `clickup_list_id`. Blank means chat posting is a
no-op, mirroring how a blank `clickup_list_id` disables task creation.

Two ways to populate it, both landing in the same field:

- **Create it for me** — a button on the ClickUp settings card. Digivault resolves
  the workspace via `GET /v2/team`, matches team members to ClickUp members, and
  calls `POST /v3/workspaces/{id}/chat/channels` with `visibility: "PRIVATE"` and
  the matched `user_ids`. Stores the created channel's URL.
- **Paste a link** — for teams who made the channel by hand. Validated through the
  existing `parse_clickup_chat()` regex; a link that does not parse is rejected
  with a field error rather than silently stored.

`parse_clickup_chat` moves from `apps.monitors.notifications` to
`apps.integrations.clickup` so `monitors` is no longer the home of a shared
ClickUp helper. `apps.monitors.notifications` re-exports it, keeping the existing
import path in [tests/monitors/test_clickup_post.py](../../../tests/monitors/test_clickup_post.py)
working.

### 2. `ClickUpMemberLink` — Digivault user → ClickUp member

```
ClickUpMemberLink(BaseModel)
    team              FK accounts.Team
    user              FK accounts.User
    clickup_user_id   CharField(32)
    clickup_username  CharField(120, blank)
    unique_together   (team, user)
```

Lives in `apps/integrations/models.py` next to `ClickUpTaskLink`.

Populated by `sync_member_links(team)`: reads workspace members from
`GET /v2/team`, matches on lowercased email against team members, upserts a link
per match. Runs when the channel is created and on demand from settings.

A member with no link is simply not mentionable — messages still post, just
unaddressed. Email mismatches are the expected failure and are not always fixable
in ClickUp, so `clickup_user_id` is editable per member (see §5).

### 3. `apps/integrations/chat.py` — the new module

Three small functions with one job each. No DB writes, no Celery.

```python
def resolve_owner(website) -> User | None
```
The developer accountable for a website: `website.client.assigned_to`. Returns
`None` when the site has no client or the client is unassigned.

```python
def mention_for(team, user) -> tuple[str, str | None]
```
`(display_text, clickup_user_id)` for a user. `display_text` is `@username` when
a `ClickUpMemberLink` exists, else the user's name or email unprefixed — so the
message never renders a broken-looking `@` for an unmapped person.
`clickup_user_id` is `None` when unmapped.

```python
def notify_problem(website, *, subject, title, detail, tags=None) -> bool
```
The single entry point every alert path calls.

1. Resolve the team's chat target from `Team.clickup_chat_url`; return `False` if
   unset or unparseable.
2. `report_issue(team, subject, title=title, body=detail, tags=tags,
   assignees=[owner_clickup_id] if mapped)` — opens or comments on the task.
3. Build the markdown body and `post_chat(...)`, passing
   `followers=[owner_clickup_id]` when mapped, so the owner is notified
   regardless of inline mention support.
4. Return whether a message was sent.

`ClickUpClient.post_chat` gains an optional `followers` parameter, sent only when
non-empty (matching how `create_task` already omits a null `assignees`).

Message shape:

```
🔴 **Example Co** — site is DOWN
example.com · owner: @jane
Down since 14:02 UTC. HTTP 503 from https://example.com/
→ https://app.clickup.com/t/86a1b2c3
```

The task link line is omitted when `report_issue` returns `None` (team has no
issue list configured, or ClickUp errored).

### 4. Wiring the existing alert paths

One added `notify_problem(...)` call per site. All additive — existing
per-website `NotificationChannel` routing is untouched.

| Source | Call site | Subject key |
|---|---|---|
| Uptime down / degraded | `notify_status_change` — [apps/monitors/notifications.py:167](../../../apps/monitors/notifications.py#L167) | `monitor:<id>:down` |
| Domain / SSL / hosting expiry | `deliver_domain_alert` — [apps/domains/notifications.py:63](../../../apps/domains/notifications.py#L63) | `domain:<id>:<alert_type>` |
| SEO / site health regression | `notify_team` — [apps/site_health/notifications.py:14](../../../apps/site_health/notifications.py#L14) | `sitehealth:<website_id>:<check>` |

Script-change alerts are **deliberately excluded** — a third-party script diff on
every ingest would drown a shared team channel. They keep their existing
per-website channels.

Recovery closes the loop: when a monitor returns to `up`, the open
`ClickUpTaskLink` for `monitor:<id>:down` is closed (so the next outage opens a
fresh task, which is exactly what `ClickUpTaskLink.close()` exists for) and a
recovery line is posted to the channel.

`notify_team` in `site_health` currently takes only `(website, subject, body)`
and has no stable per-check key. It gains a `subject_key` keyword argument;
callers that omit it get chat posting skipped rather than a task per alert body.

### 5. Settings UI

Extends the existing ClickUp card in
[frontend/src/components/settings-client.tsx](../../../frontend/src/components/settings-client.tsx),
below the "Issue list" field. No new page.

- **Team channel** — when unset, a **Create web team channel** button plus a
  "paste a link instead" input. When set, the channel link with an "Open in
  ClickUp" affordance, a **Change** action revealing the same paste input, and a
  **Clear** action that blanks the field and returns chat posting to a no-op.
- **Member mapping** — after a create or sync, the matched count plus a list of
  members with no ClickUp match. Each unmatched row has an inline ClickUp user id
  input, because an email mismatch is often not fixable on the ClickUp side. A
  **Re-sync** action re-runs matching without recreating the channel.

Backend surface, following the shape of the existing `clickup-test` route:

- `PATCH /api/v1/auth/teams/<pk>/settings/` accepts `clickup_chat_url`. Same
  independent-field handling as the existing fields — a PATCH carrying only the
  chat url must not clear the token or list id. An empty string is a valid,
  intentional clear.
- `POST /api/v1/auth/teams/<pk>/settings/clickup-channel/` creates the channel
  and syncs member links. Returns the channel url plus
  `{matched: [...], unmatched: [...]}` for the UI.
- `POST /api/v1/auth/teams/<pk>/settings/clickup-members/` re-runs
  `sync_member_links` and, when the body carries
  `overrides: [{user_id, clickup_user_id}]`, upserts those links directly.
  Returns the same matched/unmatched shape.

Both new endpoints are manager-or-higher, matching the PATCH permission check at
[apps/accounts/views.py:848](../../../apps/accounts/views.py#L848), and each gets a
Next.js proxy route under `frontend/src/app/api/teams/[id]/settings/`, copied from
the existing `clickup-test` route.

`TeamSettingsSerializer` exposes `clickup_chat_url` and a derived
`clickup_chat_connected` boolean.

## Error handling

Every ClickUp call is best-effort and must never surface in an alert path — the
contract `report_issue` already follows. `notify_problem` catches `ClickUpError`
and `Exception`, logs with `logger.exception`, and returns `False`. A team with no
token, no chat url, or no issue list is a silent no-op, not a warning: an
unconfigured team is the normal case.

The one place errors *are* surfaced is the settings UI. Channel creation is user
initiated, so a failure returns HTTP 400 with ClickUp's message — the same
pattern `ClickUpTestView` uses.

## Testing

Reuses the `RecordingSession` fake from
[tests/integrations/test_clickup_tasks.py](../../../tests/integrations/test_clickup_tasks.py) —
it records requests without patching globals, so no new network mocking is
needed and the autouse `no_network_in_tests` fixture stays sufficient.

`tests/integrations/test_chat.py`

- `resolve_owner` returns the client's assignee; `None` for a website with no
  client, and for a client with `assigned_to` unset.
- `mention_for` returns `@username` with a link, and a bare name without one.
- `notify_problem` posts to the parsed workspace/channel and includes the owner's
  ClickUp id in `followers`.
- The body includes the task URL when a task was opened, and omits the line when
  `report_issue` returns `None`.
- An unset `clickup_chat_url` sends nothing and returns `False`.
- A `ClickUpError` from `post_chat` is swallowed; `notify_problem` returns `False`.

`tests/integrations/test_member_links.py`

- `sync_member_links` matches on lowercased email and upserts idempotently.
- Workspace members with no matching Digivault user are ignored.

`tests/accounts/test_clickup_channel.py`

- Channel creation posts `name` + matched `user_ids`, stores the returned url, and
  reports matched/unmatched members.
- A viewer-level member gets 403 on both new endpoints.
- An invalid pasted chat link is rejected by the PATCH.
- A PATCH carrying only `clickup_chat_url` leaves token and list id intact.
- A PATCH with `clickup_chat_url: ""` clears the field and stops chat posting.
- `clickup-members` with `overrides` upserts a link for a member ClickUp did not
  match by email.

Per-path wiring tests assert `notify_problem` is called with the right subject
key for an uptime outage and a domain expiry, and that a recovery closes the open
`ClickUpTaskLink`.

## Out of scope

- Script-change alerts in the shared channel (see §4).
- Per-website developer assignment — `Client.assigned_to` is the owner notion.
  A site needing a different owner than its client is a future change to
  `resolve_owner` alone.
- OAuth. The token stays a personal `pk_…` token, so everything Digivault creates
  is attributed to whoever owns it — the tradeoff already documented in
  [apps/integrations/clickup.py](../../../apps/integrations/clickup.py).
- Reading replies back out of ClickUp Chat. Delivery is one-way.
