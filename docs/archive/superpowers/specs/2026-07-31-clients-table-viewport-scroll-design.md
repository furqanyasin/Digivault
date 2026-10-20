# Clients table — pin the horizontal scrollbar to the viewport bottom

**Date:** 2026-07-31
**Status:** Approved
**Scope:** `frontend/src/components/clients-client.tsx` only

## Problem

The clients table wrapper is `<div className="overflow-x-auto">` around a
`min-w-[1500px]` table. That div grows to the full height of every rendered row,
so its horizontal scrollbar sits at the bottom of the *table*, not the screen.

With "Per page" at 25, 50, or 100, the bar is thousands of pixels below the fold.
To scroll the table sideways you must first scroll the page down past the last
client, drag the bar, then scroll back up to read the rows you care about.

The dashboard `<main>` is normal document flow, so the page itself scrolls and
carries the bar away with it.

## Solution

Turn the page root into a viewport-tall flex column that does not scroll. Only
the table pane scrolls, so its scrollbar is always at the bottom of the screen.

```
<div className="h-dvh flex flex-col overflow-hidden p-8 gap-6">
  header (title + CSV buttons)        shrink-0
  import message                      shrink-0
  Quick Lookup card                   shrink-0
  filters row (All/Active, Per page)  shrink-0
  <Card>                              flex-1 min-h-0 flex flex-col   ← the pane
    <CardContent p-0>                 flex-1 min-h-0
      <div>                           h-full overflow-auto
  pagination                          shrink-0
```

### Why `min-h-0` is load-bearing

Flex items default to `min-height: auto`, which refuses to shrink below content
height. Without `min-h-0` on both the Card and the CardContent, the Card grows to
the full height of all rows, the inner `overflow-auto` never engages, and the
scrollbar stays exactly where it is today. This is the single most common way
this pattern silently fails.

### Why `h-dvh` not `h-screen`

`100vh` ignores mobile browser chrome and would push the pane bottom (and its
scrollbar) below the visible area — reintroducing the bug on small screens.
`h-dvh` tracks the actual viewport.

### No change to the dashboard layout

The page root pins its own height, so `app/(dashboard)/layout.tsx` is untouched
and every other dashboard page keeps scrolling normally. `FeatureGuard`, rendered
above `{children}`, returns `null`, so it adds no height.

## Sticky header

Once the pane is the scroll container, `top-0` resolves to the pane's top, so the
header row can stick. This matters when scanning 100 rows across adjacent date
columns ("Hosting renewal" / "Domain renewal").

The first column is already pinned left, so the z-index ladder must be explicit:

| Cell | Sticks | z-index |
|---|---|---|
| Client header (corner) | left + top | `z-30` (was `z-20`) |
| Other headers | top | `z-20` (new) |
| Client body cells | left | `z-10` (unchanged) |
| Other body cells | — | auto |

The corner cell must outrank both others or it is overlapped during diagonal
scrolling. Sticky cells need an opaque `bg-card` or rows show through underneath.

## Overflow safety

With `overflow-hidden` on the root, anything taller than the viewport in the
fixed section would be clipped with no way to reach it. Quick Lookup can return
several client results and grow unbounded, so its results list is capped at
`max-h-[38vh] overflow-y-auto`. The search form stays fixed above it.

## Non-goals

- **Columns still overflow horizontally.** `min-w-[1500px]` is unchanged; this
  moves *where the scrollbar lives*, it does not make 11 columns fit a laptop.
  Squeezing them would make the table unreadable.
- **Other tables unchanged.** `monitors/page.tsx`, `forms-tab.tsx`, and
  `performance-tab.tsx` share the `overflow-x-auto` pattern and the same latent
  issue, but are narrower and shorter. Left alone.
- **The page no longer scrolls.** Title, Quick Lookup, and Add client stay on
  screen permanently. Accepted trade-off; Quick Lookup already collapses to give
  height back to the grid.

## Verification

At a 1366x768 laptop viewport with Per page = 100:

1. Horizontal scrollbar sits at the bottom of the screen, not after the last row.
2. Header row stays visible while scrolling down.
3. Client column stays pinned while scrolling right.
4. The corner cell stays on top during diagonal scroll.
5. Collapsing/expanding Quick Lookup resizes the pane without clipping.
