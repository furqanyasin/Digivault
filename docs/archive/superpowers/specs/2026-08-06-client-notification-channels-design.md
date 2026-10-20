# Client Notification Channels — Design

**Date:** 2026-08-06
**Status:** Approved for planning

## Problem

`NotificationChannel` is team-scoped and drives uptime, domain/SSL, SEO and script
alerts, but its only entry point is a "Channels" button on the Uptime Monitors
page. Monitors is not even in the sidebar anymore — it was folded into each
website's Uptime tab (`frontend/src/app/(dashboard)/layout.tsx:22-23`) — so the
page is reachable only by deep link. The button both misrepresents the feature's
scope and hides it.

Separately, alert routing has two tiers (website, team) but the agency works in
three: an agency manages **clients**, each client has **websites**. There is no
way to say "everything for Acme goes to Acme's channel." Every one of a client's
sites must be configured one at a time.

## Goals

1. Move Channels out of Monitors to a top-level `/channels` section.
2. Give `Client` its own channel configuration.
3. Have a website inherit its client's channel when it sets none of its own.
4. Surface, everywhere a channel is shown, which channel will actually fire and
   where it came from.
5. Make the shared ClickUp feed readable per client — every message and task
   leads with the client name and assigns the responsible developer.

## Delivery target

All alerts go to **ClickUp for now**, through a **single shared channel** — not
one channel per client. Separation is per *message*, not per channel: the feed
stays one stream, but every entry states which client it belongs to and pings
that client's developer.

This rules out per-client ClickUp channel auto-creation. `create_chat_channel`
(`apps/integrations/clickup.py:128`) stays used only by the existing team-channel
endpoint.

## Non-goals

- Many-to-many channels per client. `Website` is single-channel; a set-valued
  client tier makes "which tier wins" ambiguous. The per-monitor
  `MonitorNotificationRule` union already covers multi-destination cases.
- Per-client alert-rule granularity (`notify_on_down` and friends). Those govern
  *which events* fire; this work governs *where they go*. Keeping them separate
  keeps the inheritance chain single-axis.
- Per-client ClickUp channels. One shared channel is the requirement; see
  *Delivery target*. `_announce_in_team_channel` keeps firing for every site
  regardless of channel config — only its message content changes (§5).
- Threaded ClickUp messages. "Separate message per client" means each entry is
  labelled by client, not that replies nest into per-client threads. Each problem
  already posts its own message; threading would need a different v3 endpoint and
  buys nothing while the labelling gap is the actual problem.
- Wiring `Client.notify_desktop` / `notify_email` into delivery. With everything
  on ClickUp there is no email or in-app traffic for them to suppress, so the
  logic would be unobservable. The false "honored by alert delivery" docstring
  (`apps/clients/models.py:85`) still gets corrected, and the fields stay in the
  CSV round-trip untouched. Revisit when email channels are introduced.
- Per-client ClickUp *task lists*. `report_issue` files into the team's single
  `clickup_list_id`; chat labelling does not require tasks to follow.
- Relocating `NotificationChannel` out of `apps/monitors`. It would churn every
  FK and import for no behavioral gain.

## Architecture

### 1. Data model

One nullable FK on `Client` (`apps/clients/models.py`):

```python
notification_channel = models.ForeignKey(
    "monitors.NotificationChannel", null=True, blank=True,
    on_delete=models.SET_NULL, related_name="+",
)
```

**One FK, not two.** `Website` has a second `uptime_notification_channel` so a
site can split noisy downtime off from content alerts. At the client tier that
second field would sit empty forever: everything routes to one ClickUp channel.
Adding it later is one field plus one line in the resolver, so the symmetry is
not worth carrying now.

One migration in `apps/clients/migrations/`. Requires `pytest --create-db`.

**Known limitation.** While every client points at the same shared ClickUp
channel, setting this field has no observable effect — it is the affordance that
makes "route Acme somewhere else" a config change rather than a rewrite, and it
is what the client page needs in order to show a channel at all. Readability of
the shared feed is delivered by §5, not by this field.

### 2. Resolution

The chain is currently duplicated: `resolve_channels()` for general alerts
(`apps/monitors/notifications.py:141`) and a hand-rolled inline chain for uptime
(`apps/monitors/notifications.py:178-188`). Both collapse into one resolver.

Tier-first ordering — **first non-empty tier wins**:

| purpose | order |
|---|---|
| `general` (scripts, domain/SSL, SEO) | website → client → team active channels |
| `uptime` | website.uptime → website → client → *stop* |

Within a tier, the uptime-specific channel beats the general one. Across tiers,
the more specific tier always wins. The client tier has a single channel, so
`uptime` reaches it only after both website fields are exhausted.

Uptime keeps its existing no-team-fallback behavior. That was a deliberate noise
decision — a team-wide default should not receive every downtime blip — and
adding a client tier does not change the reasoning.

An **inactive** channel falls through to the next tier rather than muting the
site. Deactivating a channel must never silently stop alerts.

```python
class ChannelResolution(NamedTuple):
    channels: list      # NotificationChannel
    source: str         # website | website_uptime | client | team_default | none
    source_label: str   # "Acme Ltd (client)" — for the UI

def resolve_channel_source(website, *, purpose="general") -> ChannelResolution
def resolve_channels(website, *, purpose="general") -> list   # thin wrapper
```

Keeping `resolve_channels` as a list-returning wrapper with its existing default
means `apps/domains/notifications.py:107` and `apps/site_health/notifications.py:24`
need no edits and inherit the client tier for free.

`notify_status_change` drops its inline chain for
`resolve_channels(website, purpose="uptime")`. Per-monitor
`MonitorNotificationRule` extras still union on top, deduped by channel id.

### 3. Dead client toggles — docstring only

`Client.notify_desktop` / `notify_email` (`apps/clients/models.py:85-87`) are
documented as "honored by alert delivery" and are not. They are written by the
CSV import (`apps/clients/views.py:451`), read by the CSV export
(`apps/clients/views.py:549`), and editable in the client UI — but read by zero
delivery paths.

Wiring them is deliberately **out of scope** (see Non-goals): with all traffic on
ClickUp there is no email or in-app delivery for them to suppress, so the logic
would be untestable against real behavior. Correct the misleading docstring to
say the fields are stored for CSV round-trip and not yet consumed. Leave the
fields, the import/export, and the UI toggles alone.

### 4. API

- `ClientSerializer` — `notification_channel` plus `notification_channel_name`,
  with same-team validation. The `_validate_team_channel` helper at
  `apps/websites/serializers.py:96` moves to a shared mixin in
  `apps/common/serializers.py` rather than being copy-pasted.
- `ClientSerializer`, **detail only** — `websites: [{id, name, domain,
  notification_channel, uptime_notification_channel}]`, guarded by
  `view.action == "retrieve"` (the pattern `get_status_page` already uses to
  avoid an N+1 on the list). No new query filter needed.
- `WebsiteSerializer`, **detail only** — read-only
  `effective_notification_channel` and `effective_uptime_notification_channel`,
  each `{id, name, channel_type, source, source_label}`.
- `NotificationChannelSerializer` — read-only `usage: {clients, websites,
  monitors}`, annotated in the list queryset.

### 5. Frontend

- **New** `/channels` route carrying the existing `/monitors/channels` content
  and reusing `NotificationChannelsClient`, plus a usage column so the blast
  radius is visible before deleting or deactivating a channel.
- `/monitors/channels/page.tsx` becomes `redirect("/channels")` so existing
  bookmarks and deep links survive.
- Remove the button at `frontend/src/app/(dashboard)/monitors/page.tsx:63-68`.
- Sidebar: `{ href: "/channels", label: "Channels", icon: "channels",
  feature: "alerts" }` after Alerts, plus `channels: "alerts"` in `ROUTE_FEATURE`
  (`frontend/src/components/feature-guard.tsx:8`). Reusing the existing `alerts`
  feature key avoids adding a `FEATURE_KEYS` entry and backfilling every member's
  `feature_access` — channels are where alerts go.
- **Client detail** (`frontend/src/components/client-detail-client.tsx`) — new
  "Alerts & Channels" card: one selector, inline help describing the chain, and
  the client's websites listed as *inherits* vs *overrides*.
- **Website detail** (`frontend/src/components/website-alerts-status.tsx`) — add
  the uptime selector it currently lacks, and replace the misleading
  "Team default channels" placeholder with the real resolved source, e.g.
  "Inherited from client: Acme Ltd".

### 6. ClickUp feed readability

One shared channel carries every client's problems, and today a message names
only the site: `_build_message` (`apps/integrations/chat.py:60`) uses
`website.name or website.domain` and `website.domain`. Nothing states which
client account the site belongs to, which is what makes the shared feed hard to
scan.

Already working and left alone: each problem posts its own message; the
responsible developer is resolved from `Client.assigned_to`
(`apps/integrations/chat.py:26`), rendered as `@username`, passed as a ClickUp
`follower` (the thing that actually pings them), and set as the task assignee.

Changes:

- `_build_message` leads with the client name, falling back to the site label
  when a website has no client:

  ```
  🔴 **Acme Ltd** — acme.com is DOWN
  client: Acme Ltd · site: acme.com · owner: @dev
  → <task url>
  ```

- `report_issue`'s task title is prefixed with the client name so the ClickUp
  list is scannable by account too, and the client name is added to `tags`
  alongside the existing tags.
- `notify_recovery` gets the identical treatment — the recovery message must
  match the problem message it clears, or the pair is unscannable.

`subject` (the dedupe key) is unchanged. It is keyed on monitor/website ids, and
changing it would orphan every open `ClickUpTaskLink`.

## Testing

- `tests/monitors/test_channel_resolution.py` — table-driven across the matrix:
  website-only, client-only, both, inactive channel at each tier, no client,
  nothing set anywhere; each run for both `general` and `uptime`. Asserts the
  chosen channel *and* the reported source.
- `tests/clients/` — serializer accepts a same-team channel, rejects another
  team's, and exposes the website list only on retrieve.
- `tests/websites/` — retrieve exposes the effective channel and source.
- `tests/integrations/` — the problem message, the recovery message and the task
  title all carry the client name; a website with no client falls back to the
  site label instead of rendering an empty segment; `subject` is unchanged so an
  existing open `ClickUpTaskLink` still dedupes onto the same task.
- Model change: run `pytest --create-db`.

## Risks

- **Behavior change for existing installs.** A website with no channel whose
  client gains one silently starts routing to the client channel instead of the
  team defaults. This is the intended outcome, but it is a routing change on
  live alerting — the source badge in the UI is what makes it legible.
- **The client FK is inert on day one.** Every client points at the same shared
  ClickUp channel, so the new selector changes nothing observable until a second
  destination exists. Documented in §1; the readability win comes from §6. If the
  plan needs trimming, §1–§4 are the deferrable half and §6 is not.
- **Message format is load-bearing for humans, not machines.** Nothing parses
  these strings, so the risk is only that a badly-shaped line reads worse than
  today's. The recovery message must be changed in lockstep with the problem
  message.
