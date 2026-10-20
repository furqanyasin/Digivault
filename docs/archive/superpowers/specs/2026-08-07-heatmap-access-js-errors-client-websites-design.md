# Heatmap access, JS Errors removal, client websites — design

Date: 2026-08-07

Three unrelated dashboard corrections, grouped because they are small and land in
adjacent files.

## 1. Heatmap becomes a grantable section

**Problem.** The per-member "Sections this member can open" chip list offers
Clients, Websites, Renewal Center, Alerts, Credentials and Activity Log. Heatmap
is missing, because the sidebar item is `always: true` — every member sees it and
no manager can take it away.

**Design.**

- `apps/accounts/features.py` — add `"heatmap"` to `FEATURE_KEYS`. `_ALL` and
  `_MEMBER` derive from that set, so every role except `custom` picks it up in its
  default preset automatically.
- New data migration `accounts/0012` — append `"heatmap"` to `feature_access` on
  memberships that already store a non-empty list and whose role is not `custom`.
  Without this, adding a key silently revokes the section from every member who
  had ever been fine-tuned, since `effective_features` returns the stored list
  verbatim once it is non-empty. `custom` members are left alone: their empty-by-
  default list is the whole point of that role, and anything they do hold was
  granted deliberately.
- `frontend/src/app/(dashboard)/layout.tsx` — the Heatmap nav item drops
  `always: true` and gains `feature: "heatmap"`.
- `frontend/src/components/feature-guard.tsx` — add `heatmap: "heatmap"` to
  `ROUTE_FEATURE`, so typing the URL redirects the same way the sidebar hides it.
- `frontend/src/components/team-management-client.tsx` — add
  `{ key: "heatmap", label: "Heatmap" }` to `FEATURES`.

The page itself stays the "Coming soon" placeholder; this is purely about who can
reach it.

## 2. JS Errors tab removed

**Problem.** The website detail page shows a "JS Errors (n)" tab. It should not
appear for anyone.

**Design.** Remove the UI only — collection stays intact.

- `frontend/src/app/(dashboard)/websites/[id]/page.tsx` — drop the
  `/api/v1/websites/{id}/js-errors/` fetch from the `Promise.allSettled` batch,
  the `jsErrors` key on the returned object, its destructure, the `TabsTrigger`
  and the `TabsContent`, and the `JsErrorsTab` import.
- Delete `frontend/src/components/js-errors-tab.tsx` — nothing else imports it.

The `JsError` model, the ingest path in `apps/scripts/` and the
`/js-errors/` endpoint are untouched. Errors keep accumulating and the tab can be
restored by re-adding the two JSX blocks. Dropping the fetch also removes one
request from the page's fan-out.

## 3. Client detail lists that client's websites

**Problem.** `/clients/<id>` renders an edit form and nothing else. Opening a
client tells you nothing about the site being monitored for them — the exact thing
a viewer goes there for.

**Design.**

- `frontend/src/app/(dashboard)/clients/[id]/page.tsx` — fetch
  `api.getAll<Website>("/api/v1/websites/")` alongside the client and filter to
  `w.client === id`. There is no `?client=` filter on the websites viewset and the
  list is team-scoped and small, so filtering client-side in the server component
  avoids a backend change.
- New `frontend/src/components/client-websites-card.tsx` — a card listing each
  matched site: name and domain linking to `/websites/<id>`, status badge, health
  score, active script count, 30-day uptime. Empty state when the client has no
  monitored site, pointing at `/websites/new`.
- `frontend/src/components/client-detail-client.tsx` renders the card below the
  form.

Shown to every role, not just viewers — it is read-only information and the
Clients section is already feature-gated. A viewer with the Clients chip sees it;
anyone without the chip never reaches the page.

## Testing

- Backend: extend the existing accounts feature-access tests to assert `heatmap`
  is in the default preset for a non-custom role and absent for `custom`, and that
  the migration backfills a fine-tuned membership.
- Frontend: `npm run lint` and `npm run build` — these are server components with
  no branching logic worth a unit test.
