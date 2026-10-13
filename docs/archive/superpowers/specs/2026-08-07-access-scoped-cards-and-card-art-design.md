# Access-scoped cards, developer activity log, and credential card art

**Date:** 2026-08-07
**Status:** Approved

Three independent changes, unified by one rule: **a member should never see a
card, tile or list built from data they have no access to** — and where the
data is legitimately theirs, they should get the page that owns it.

Frontend-only, except for one test.

---

## 1. Credential card art — monogram instead of a lock

### Problem

`CardArt` in `frontend/src/components/credentials-vault-client.tsx` renders a
favicon from Google's `s2/favicons` service and falls back to a `Lock` icon.
Two different failures land on that same lock:

- **No `login_url`** on the credential — `hostFromUrl()` returns `null`, so the
  image is never attempted. This is the common case and the one users notice.
- **The image errors** — network failure, blocked request.

- **The domain has no favicon** — Google's service answers **HTTP 404** for
  these (verified: `example.com` and a nonexistent domain both 404; `github.com`
  and `neverssl.com` return real icons), so `onError` fires and the card lands
  on the lock.

The result is a vault grid where visually identical cards mean three unrelated
things, and a lock — the icon for "this is a secret" — is doing duty as an
error state.

### Design

`CardArt` renders a **monogram as the base layer** with the favicon image
absolutely positioned on top. When the image fails it unmounts and the monogram
is already in place — no state flash, no lock.

Monogram rules:

- Source text is `cred.label`; take the first character of up to two
  whitespace-separated words, uppercased, max 2 characters.
- Fall back to the credential type label, then to `?`.
- This mirrors the existing `initials()` helper in
  `frontend/src/app/(dashboard)/logs/page.tsx`, so the two agree.

Style: `text-white/85`, semibold, in the same 40×40 rounded box the favicon
occupies, over the card's existing `cardColor(cred)` background. The monogram
is `aria-hidden` — the card body already names the credential, so announcing
the initials would be a duplicate.

### Favicon source

**Google's `s2/favicons` is kept.** The design originally assumed it answered
200 with a generic globe for icon-less domains, which would have meant `onError`
never fired and a second service was needed to detect the case. That assumption
was wrong — it returns 404, so `onError` already fires and the existing
fallback path is reached. The monogram therefore covers every failure mode on
its own, with no extra request and no second provider.

---

## 2. Developers get their own Activity Log

### Problem

`apps/audit/views.py::_scoped_logs` already does the right thing: managers and
owners see the whole team (optionally filtered by `?user_id=`), and **everyone
else sees only their own rows**. A non-manager's `?user_id=` is ignored. The
CSV export path shares the same function.

The frontend does not use any of that. `/logs` is marked `managerOnly` in the
sidebar and listed in `MANAGER_ONLY` in the route guard, and the page itself
refuses to render for non-managers. So a developer has a correctly-scoped
endpoint and no way to reach it — while the dashboard "Recent activity" card
shows them those same rows.

### Design

**No backend change.** The scoping is already correct and is the security
boundary; the frontend was hiding a page it did not need to hide.

- `frontend/src/app/(dashboard)/layout.tsx` — `/logs` drops `managerOnly` and
  keeps `feature: "activity_log"`. The sidebar item appears for any member
  granted that feature.
- `frontend/src/components/feature-guard.tsx` — remove `"logs"` from
  `MANAGER_ONLY`. It is already in `ROUTE_FEATURE`, so the feature grant
  governs access, as it does for every other section.
- `frontend/src/app/(dashboard)/logs/page.tsx`:
  - Delete the "Managers only" refusal screen. **Keep the `roleError`
    branch** — that one reports a genuine failure to read the role and is not a
    permission decision.
  - Drop `isManager` from the fetch effect's guard so non-managers actually
    load data.
  - For non-managers: title "My activity", subtitle "Your actions — N events".
  - For non-managers: hide the **Who** column and its member filter, and skip
    the `/api/teams/{id}/members` request entirely — it exists only to populate
    that filter.
  - Render the **Client** and **Website** filter columns only when `clients` /
    `websites` are in the member's features. The page already fetches
    `/api/auth/teams`, which carries `my_features`, so this costs no request.

Managers and owners see exactly what they see today.

### Why not hide the card instead

Hiding the "Recent activity" card and leaving `/logs` manager-only was the
alternative. It is simpler but strictly worse: a developer loses all visibility
into their own actions, including the security-relevant ones (their own logins,
their own credential reveals). The backend already distinguishes "your actions"
from "the team's actions"; the UI should too.

---

## 3. Dashboard cards match access

### Problem

`frontend/src/app/(dashboard)/dashboard/page.tsx` computes `isOwner`,
`isManager` and `can(feature)` and applies them to the summary chunks, the
alerts card and the side card — but four cards ignore them entirely.

### Design

Gate each on the feature its data comes from:

| Card | Gate |
| --- | --- |
| Website health donut | `can("websites")` |
| Uptime | `can("websites")` — monitors are a website detail tab, not a section of their own |
| Needs attention | `can("websites")` |
| Recent activity | `can("activity_log")` |

The "Activity log" button inside the Recent activity card drops its
`isManager &&` prefix and keeps `can("activity_log")`, matching change 2.

Grid widths follow the conditional `lg:grid-cols-*` pattern the page already
uses for `can("alerts")` and `sideCard`, so a hidden card closes the gap rather
than stranding its neighbour in an over-wide track. A row whose children all
hide does not render at all.

### Empty state

A member with none of these features would otherwise get a page with a header
and nothing under it. When no card survives, render a single card reading
"Nothing's been shared with you yet" with a line pointing at their team
manager.

### Scope

Dashboard cards only. Website detail tabs, client detail and settings are
deliberately out of scope — they are a larger sweep and were excluded when this
was scoped.

---

## Testing

**Backend** — `tests/accounts/test_custom_role.py` gains coverage for the claim
change 2 depends on:

- A developer's `GET /api/v1/logs/` returns only rows where they are the actor.
- A developer passing `?user_id=<another member>` still gets only their own
  rows — the parameter is ignored, not honoured.

The code already behaves this way. The test exists because change 2 makes the
frontend rely on it, and a regression there would leak one member's activity to
another.

**Frontend** — the repo has no frontend test infrastructure. Verified by
`npm run lint` and `npm run build`, plus manual checks signed in as a
developer-role member and as a custom member with `activity_log` revoked.
