# Client Notification Channels — Review Addendum

**Date:** 2026-08-06
**Reviews:** [2026-08-06-client-notification-channels-design.md](./2026-08-06-client-notification-channels-design.md)
**Status:** Findings for the implementing agent. Does not supersede the design.

Written from a second, independent read of the same code. The design's claims were
spot-checked and hold — including the finding that `Client.notify_email` /
`notify_desktop` are decorative (`apps/clients/views.py:451-452, 485-486, 549-550`
and `apps/clients/serializers.py:41` are their only readers). Three things the
design does not cover.

## F1 — `/channels` gated by `feature: "alerts"` exposes API tokens (blocking)

The design puts the library at a top-level `/channels` with
`{ href: "/channels", feature: "alerts" }` and `channels: "alerts"` in
`ROUTE_FEATURE`. Reusing the `alerts` key to avoid backfilling `feature_access` is
a good call for the routing, but it **widens who can read channel secrets**.

`NotificationChannelSerializer` returns `config` raw
(`apps/monitors/serializers.py:10`), and `config` holds the credentials:

| type | config contents |
|---|---|
| `clickup` | `api_token` — full workspace API token (`notifications.py:70`) |
| `slack` | `webhook_url` — post-anywhere URL (`notifications.py:101`) |
| `email` | `addresses` |

Today the page sits under `/monitors`, so `FeatureGuard` gates it on the
`monitors` feature (`frontend/src/components/feature-guard.tsx:11`, first path
segment only — `:38`). Re-keying to `alerts` hands a ClickUp workspace token to
every custom member granted alert visibility. `alerts` is a *read* feature —
seeing notifications — and channel config is credentials.

Contrast `WebsiteSerializer`, which deliberately never emits `wp_sso_secret` and
exposes only `wp_sso_configured` (`apps/websites/serializers.py:85-86`). Channels
should follow that precedent.

**Fix, independent of where the route lives:**

1. Mask `config` on read in `NotificationChannelSerializer` — return
   `config_masked` (last 4 of `api_token`, host-only for `webhook_url`, addresses
   in full) plus a `config` that stays **write-only**. This is the smaller change
   and it fixes the leak at the source for every consumer, including the existing
   `/monitors/channels` page.
2. Gate the route `managerOnly`, matching `team` and `logs`
   (`feature-guard.tsx:22`). Channel config is team configuration, like the
   ClickUp token already living in Settings.

Do both. (1) alone still lets a non-manager add or delete a channel; (2) alone
leaves tokens in the JSON for anyone who is a manager on a shared account, and
leaves the current page leaking until it is removed.

An alternative placement is `/settings/channels`, which puts it beside the
existing team ClickUp token. Be aware `settings` is in `FeatureGuard`'s `ALWAYS`
set (`feature-guard.tsx:26`) and gating is by first segment only, so a
`/settings/*` subroute is reachable by **every** user and must be role-gated
server-side in the page — the way `settings/page.tsx:31` only fetches team
settings for managers. Top-level `/channels` + `managerOnly` avoids that trap and
is the cleaner of the two.

## F2 — `Client.uptime_notification_channel` is worth reconsidering

The design adds two FKs to `Client` to mirror `Website` exactly. Symmetry is a
real benefit and the fallback walk does get simpler, so this is a judgement call,
not an error. The case for one FK:

The uptime/general split exists at the *website* level for a concrete reason — one
site may want downtime paged loudly while script-change noise goes elsewhere. At
the *client* level, "all of Acme's downtime goes here, all of Acme's other alerts
go there" is a distinction no agency workflow has asked for, and it doubles the
resolution matrix: the design's own test plan already spans two purposes × four
tiers × active/inactive.

If it ships as two FKs, the second one must be visibly optional in the client UI
(collapsed, "advanced") or every client form asks a question nobody has an answer
to. Whichever way it goes, decide before writing the test matrix — retrofitting
`client_uptime` into the table afterwards is the expensive order.

## F3 — Live file conflict with the frontend pagination fix

Three frontend files were edited in a **separate session on this same branch**
(`fix/dashboard-security-and-forms`) while this design was being written, fixing
list truncation at 25 rows:

| file | change |
|---|---|
| `frontend/src/app/(dashboard)/monitors/page.tsx` | line 46 → `api.getAll`, +3 comment lines |
| `frontend/src/app/(dashboard)/status-pages/[id]/page.tsx` | line 24 → `api.getAll` |
| `frontend/src/app/(dashboard)/credentials/page.tsx` | lines 10-13 → `api.getAll` |

`monitors/page.tsx` is the overlap: the Channels button the design removes is now
at **63-68**, not 60-65, because of those inserted comment lines. The design's
line reference is already correct for the current file — just do not re-derive it
from an older read.

Apply the same fix to the new channels page: `api.getAll<NotificationChannel>`,
not `api.get`. The existing `/monitors/channels` page uses `api.get`
(`monitors/channels/page.tsx:11`) and will silently show only the first 25
channels. Same for the `fetch("/api/notification-channels")` calls in
`website-alerts-status.tsx:66` and any new client picker — that Next.js proxy
route passes no `page_size` (`frontend/src/app/api/notification-channels/route.ts:14`),
so it returns page 1 only. Add `?page_size=100` to the proxy, or the picker will
be missing channels for any team that grows past 25.

## F4 — Minor corrections

- The design cites `AlertRule.Channel` as having `in_app` and `email`. It also
  has `clickup` and `slack` (`apps/alerts/migrations/0005_...py:16`). Does not
  change the suppression logic, but `notify_email=False` must filter *only* the
  `email` rule, not "everything that is not in_app".
- `NotificationChannel`'s docstring (`apps/monitors/models.py:199-202`) documents
  discord/webhook/telegram config shapes that `ChannelType` no longer offers, and
  names slack's key `url` where the sender reads `webhook_url`. The design already
  says to fix the docstring — this is what is wrong with it.
