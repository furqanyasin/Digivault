# Form Submission Error Detection — Design

**Date:** 2026-06-10
**Status:** Approved (user-supplied spec, adapted from "Pulse"), implementing

## Problem

When a visitor submits a form and the submission fails server-side (mail not
sent, SMTP down, 5xx), the agency never finds out unless the client complains.
Detect these failures passively via the existing tracking snippet and surface
them in the dashboard.

## Detection (snippet v1.5) — passive, zero field collection

- **High-quality plugin events:** listen for Contact Form 7's
  `wpcf7mailfailed` / `wpcf7spam` DOM events — definitive failure signals.
- **Generic DOM observation:** on any capture-phase `submit`, open a ~20s
  watch window with a `MutationObserver` (childList + characterData, subtree)
  and scan newly rendered text for failure phrases (e.g. "submission failed",
  "failed to send", "could not be sent", "server error", "try again later",
  HTTP 500–504). This catches WPForms, Elementor, Gravity, Ninja, etc. without
  per-plugin integrations.
- **Source inference** from form classes (`wpcf7-form` → Contact Form 7,
  `wpforms-form` → WPForms, `elementor-form` → Elementor Forms,
  `gform` → Gravity Forms, `nf-form` → Ninja Forms, `forminator` → Forminator,
  `hs-form` → HubSpot), else "unknown".
- **Privacy guardrails:** the tracker never reads `input.value`; it captures
  only the plugin's rendered status text. One report per form per page load.

## Transport

`POST /api/ingest/form-errors/` — must live under `/api/ingest/` because the
production nginx only proxies `api/v1|api/ingest|api/php-errors|api/extension|admin|ws`
to Django. Same auth model as ingest: `site_id` identifies the website,
AllowAny + ingest throttle + origin/domain binding. Payload:
`{site_id, page_url, source, form_id, message}`.

## Server-side filtering & sanitisation

- `is_important_form_error(message)` — accept only messages containing an
  IMPORTANT keyword (submission failed / failed to send / could not be sent /
  server error / internal error / mail failed / smtp / 500–504 / try again
  later); reject pure user-validation noise (required / invalid / please fill /
  captcha…). Noise returns 202 but is not stored (no signal to probers).
- `sanitize_page_url(url)` — redact values of sensitive query params
  (email, token, key, password, phone, code, auth).
- `sanitize_error_message(text)` — redact emails, `password=…`/`token=…`
  values, and long digit runs (phones) to `[hidden]`.

## Storage

`FormSubmissionError` (apps/scripts): `website` FK, `source`, `form_id`,
`page_url` (sanitized), `message` (sanitized), BaseModel timestamps.
Index `(website, -created_at)`.

## Display

- `GET /api/v1/websites/<pk>/form-errors/` (team-scoped) + Next.js proxy.
- Website detail → **Forms tab**: a "Form Errors" card under Detected Forms
  listing recent failures (source, message, page, time). Forms tab badge count
  unchanged.

## Out of scope (v1)

- Alert-rule integration (notify on form error) — later.
- Retention/purge job — volumes are tiny after keyword filtering.
