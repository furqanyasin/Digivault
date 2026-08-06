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

## Non-goals

- Many-to-many channels per client. `Website` is single-channel; a set-valued
  client tier makes "which tier wins" ambiguous. The per-monitor
  `MonitorNotificationRule` union already covers multi-destination cases.
- Per-client alert-rule granularity (`notify_on_down` and friends). Those govern
  *which events* fire; this work governs *where they go*. Keeping them separate
  keeps the inheritance chain single-axis.
- Changes to `_announce_in_team_channel`, the shared ClickUp web-team feed. It
  fires for every site regardless of channel config by design. A per-client
  ClickUp channel is already achievable through the existing `clickup`
  `NotificationChannel` type (its config holds a `chat_url`), so no new mechanism
  is needed and the team feed keeps running alongside it.
- Relocating `NotificationChannel` out of `apps/monitors`. It would churn every
  FK and import for no behavioral gain.

## Architecture

### 1. Data model

Two nullable FKs on `Client` (`apps/clients/models.py`), mirroring `Website`
exactly so the fallback is a plain field-by-field walk:

```python
notification_channel = models.ForeignKey(
    "monitors.NotificationChannel", null=True, blank=True,
    on_delete=models.SET_NULL, related_name="+",
)
uptime_notification_channel = models.ForeignKey(
    "monitors.NotificationChannel", null=True, blank=True,
    on_delete=models.SET_NULL, related_name="+",
)
```

One migration in `apps/clients/migrations/`. Requires `pytest --create-db`.

### 2. Resolution

The chain is currently duplicated: `resolve_channels()` for general alerts
(`apps/monitors/notifications.py:141`) and a hand-rolled inline chain for uptime
(`apps/monitors/notifications.py:178-188`). Both collapse into one resolver.

Tier-first ordering — **first non-empty tier wins**:

| purpose | order |
|---|---|
| `general` (scripts, domain/SSL, SEO) | website → client → team active channels |
| `uptime` | website.uptime → website → client.uptime → client → *stop* |

Within a tier, the uptime-specific channel beats the general one. Across tiers,
the more specific tier always wins.

Uptime keeps its existing no-team-fallback behavior. That was a deliberate noise
decision — a team-wide default should not receive every downtime blip — and
adding a client tier does not change the reasoning.

An **inactive** channel falls through to the next tier rather than muting the
site. Deactivating a channel must never silently stop alerts.

```python
class ChannelResolution(NamedTuple):
    channels: list      # NotificationChannel
    source: str         # website | website_uptime | client | client_uptime | team_default | none
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

### 3. Client notification toggles

`Client.notify_desktop` / `notify_email` (`apps/clients/models.py:85-87`) are
documented as "honored by alert delivery" and are not. They are written by the
CSV import (`apps/clients/views.py:451`), read by the CSV export
(`apps/clients/views.py:549`), and editable in the client UI — but read by zero
delivery paths. They are decorative today.

They are in scope because the new channel card lands directly beside them, and
two dead toggles next to a live one reads as "channels are broken too."

**Wire them, do not remove them** — they are part of a CSV round-trip the agency
already uses, so deleting them breaks a spreadsheet contract. Both map onto real
delivery paths: `AlertRule.Channel` already has `in_app` and `email`
(`apps/alerts/models.py:14-15`).

The two toggles act on **two different systems**, and the split matters:

| toggle | `NotificationChannel` resolver | `AlertService` rules |
|---|---|---|
| `notify_email = False` | drop `email`-type channels | drop `email` rules |
| `notify_desktop = False` | *no effect* — there is no in-app channel type | drop `in_app` rules |

`NotificationChannel.ChannelType` is only `email` / `clickup` / `slack`
(`apps/monitors/models.py:205-208`), so in-app delivery exists solely in the
alerts app. `notify_desktop` therefore filters `applicable_rules` in
`AlertService.dispatch_for_change` and never touches the resolver.

Both are applied as **suppression filters after selection**, never as another
tier — the tier decides *where*, the toggle decides *whether*. In the alerts app
the natural home is beside the existing `_is_suppressed` gate
(`apps/alerts/services.py:33`), filtering `applicable_rules` by
`rule.channel` against the website's client.

Correct the model docstring at the same time.

### 4. API

- `ClientSerializer` — the two FK fields plus `*_name`, with same-team
  validation. The `_validate_team_channel` helper at
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
  "Alerts & Channels" card: both selectors, inline help describing the chain, and
  the client's websites listed as *inherits* vs *overrides*.
- **Website detail** (`frontend/src/components/website-alerts-status.tsx`) — add
  the uptime selector it currently lacks, and replace the misleading
  "Team default channels" placeholder with the real resolved source, e.g.
  "Inherited from client: Acme Ltd".

## Testing

- `tests/monitors/test_channel_resolution.py` — table-driven across the matrix:
  website-only, client-only, both, inactive channel at each tier, no client,
  nothing set anywhere; each run for both `general` and `uptime`. Asserts the
  chosen channel *and* the reported source.
- Suppression: a client with `notify_email=False` drops email channels but keeps
  ClickUp/Slack, and drops `email` alert rules; `notify_desktop=False` drops
  `in_app` rules while leaving resolved channels untouched. A website with no
  client is unaffected by either.
- `tests/clients/` — serializer accepts a same-team channel, rejects another
  team's, and exposes the website list only on retrieve.
- `tests/websites/` — retrieve exposes the effective channel and source.
- Model change: run `pytest --create-db`.

## Risks

- **Behavior change for existing installs.** A website with no channel whose
  client gains one silently starts routing to the client channel instead of the
  team defaults. This is the intended outcome, but it is a routing change on
  live alerting — the source badge in the UI is what makes it legible.
- **Suppression filter can empty a tier.** A client with `notify_email=False`
  whose only channel is email resolves to zero channels. The resolver reports
  `source="none"` and the UI must say so explicitly rather than render a blank
  dropdown.
