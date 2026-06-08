# Multi-Type Form Detection — Design

**Date:** 2026-06-09
**Status:** Approved, implementing

## Problem

The "Detected Forms" tab shows 0 forms for sites that clearly have forms (a contact
page with one form, PPC landing pages with several). Investigation confirmed the
ingest pipeline (snippet → ingest → serializer → Celery → DB → API → UI) is sound
and treats forms identically to scripts. The gap is **detection coverage** in the
snippet's `collectForms()`, which only finds native `<form>` elements via
`document.querySelectorAll('form')`.

The sites in question contain three kinds of forms:

1. **Native `<form>` elements** — Contact Form 7, WPForms, Gravity Forms, Elementor's
   native form widget, hand-coded forms.
2. **Div-based / JS forms** — inputs wrapped in `<div>`s, submitted via JavaScript,
   with no `<form>` tag.
3. **Embedded third-party forms** — HubSpot, Typeform, Jotform, Mailchimp, Google
   Forms, Calendly, etc., loaded inside an `<iframe>`.

Note: sitemap / `noindex` / `nofollow` are **irrelevant** — Digivault does not crawl a
sitemap. Forms are detected passively when a real browser loads a page carrying the
snippet. This design does not change that model; it widens what the snippet detects
on the pages it already runs on.

## Goals

- Detect all three form types when the snippet runs on a page.
- Be honest about the hard limit on embedded forms: cross-origin iframes cannot be
  read, so we capture **presence + provider only**, never field lists.
- Surface the detection method in the UI so users understand each row.

## Non-goals

- Reading fields inside cross-origin iframes (browser security boundary — impossible).
- A server-side URL/sitemap scanner for forms (separate future effort; static HTML
  can't see JS/div/iframe forms anyway).
- Detecting forms on pages where the snippet is not installed or that have never been
  opened in a browser.

## Detection logic (`collectForms` v2, `apps/scripts/snippet.js`)

Each detected form carries a `detection_type` of `native` | `dom` | `embedded` and an
optional `provider`.

- **Native:** unchanged. `querySelectorAll('form')`, collect visible fields,
  `detection_type: "native"`.
- **Div-based (`dom`):** collect visible `input/textarea/select` whose `.closest('form')`
  is null; group orphans by their nearest "form-like" container (an ancestor that
  contains a submit-style control, or has `role="form"` / a class or id containing
  "form"). Emit one form per container. Noise threshold: a group is only emitted if it
  has a submit-style control **or** ≥2 fields, so a lone search box is ignored.
  `form_action`/`form_method` are best-effort (often empty); id/name from the container.
- **Embedded:** scan `<iframe>` `src` against a provider map (HubSpot, Typeform,
  Jotform, Mailchimp, Google Forms, Calendly, Wufoo, Zoho). On match, emit
  `detection_type: "embedded"`, `provider`, `form_action = iframe.src`, `fields: []`.

Snippet version bumps to `1.4`.

## Data model (`DetectedForm`)

New fields:

- `detection_type` — `CharField(choices=native|dom|embedded, default="native")`
- `provider` — `CharField(max_length=100, blank=True)`
- `fingerprint` — `CharField(max_length=64, db_index=True)`

The current uniqueness key `(website, page_url, form_action)` **breaks** for div forms,
which all have an empty action and would overwrite each other. Replace it with
`(website, page_url, fingerprint)`.

`fingerprint = sha256("{detection_type}|{form_id}|{form_name}|{form_action}|{sorted field names}")`
truncated to 32 hex chars, computed server-side in `_upsert_form`. Stable across
re-sends of the same form (so it updates in place); a structural change yields a new
row, which is acceptable for v1.

Migration: add the three fields, backfill `fingerprint` for existing rows from a hash of
their `form_action` (preserving current uniqueness), then swap `unique_together`.

## Transport & API

- `IngestFormSerializer` accepts `detection_type` (ChoiceField, default `native`) and
  `provider` (CharField, blank, default `""`).
- The ingest view forwards both fields into the queued payload.
- `_upsert_form` computes the fingerprint, stores `detection_type`/`provider`, and uses
  `(website, page_url, fingerprint)` as the `update_or_create` key.
- `DetectedFormSerializer` exposes `detection_type` and `provider`.

## Frontend

- `DetectedForm` type gains `detection_type` and `provider`.
- `FormsTab` shows a small badge per row: `native` / `dom` / `embedded — HubSpot`.
  Embedded rows already render "—" for fields, which now reads correctly given the badge.

## Testing

- Serializer accepts and defaults the new fields.
- `_upsert_form` creates separate rows for two div forms with empty action on one page
  (distinct fingerprints).
- Embedded form is stored with its provider and empty fields.
- Re-ingesting an identical form updates in place (same fingerprint, no duplicate).

## Operational caveat (carried into UI copy / support notes)

Even with full coverage, a form only appears once the snippet is present on the page
**and** a browser has opened it. PPC landing pages on a separate tool/subdomain without
`s.js` will still show 0 until the snippet is installed there.
