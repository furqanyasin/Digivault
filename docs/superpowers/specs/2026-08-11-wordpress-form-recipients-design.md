# Reading form recipients from WordPress

**Date:** 2026-08-11
**Status:** Approved

## Problem

The Forms tab shows a "Goes to" column, filled from `DetectedForm.recipient_email`,
which the tracking snippet reads out of the page: a `mailto:` action, a recipient
`data-` attribute, or a hidden input whose name reads as a destination.

For the WordPress sites Digivault actually monitors, that column is empty. An
Elementor form's "To" address lives in the `_elementor_data` post meta of the page
it sits on. Contact Form 7 keeps it in `_mail`, WPForms in the form post's JSON,
Gravity Forms in its notification config. None of it renders into HTML, so no
in-page script can ever see it, and no amount of work on `snippet.js` will change
that.

The agency knows the address — it is in the client's WP admin, two clicks away —
but Digivault can't show it, can't alert on it changing, and can't tell the team
when a client silently repoints a lead form at a mailbox nobody reads.

## Approach

Have WordPress tell us, over the mechanism already built for this: the WP Connect
PHP snippet (`apps/websites/wp_sso_snippet.py`). The user pastes it into WPCode or
Code Snippets; it carries a per-site HMAC secret (`Website.wp_sso_secret`) and
registers routes under `digivault/v1`. Adding a second route there costs the user
one re-paste and needs no new install flow, no new secret, and no plugin.

Rejected alternatives:

- **Report at submit time** (hook `wp_mail` / `elementor_pro/forms/new_record`).
  More truthful — it captures Cc/Bcc and conditional routing — but a form shows
  nothing until someone submits it, and quiet forms are exactly the ones the
  agency most needs to check.
- **A manual field per form.** No site-side change, but manual and silently stale
  the moment a client edits the form, which defeats the point of monitoring.

## Components

### 1. `digivault/v1/forms` REST route (PHP, in the existing snippet)

Registered alongside `digivault/v1/sso`. **Authenticated with the same HMAC
scheme as SSO** — signature over a base64 payload carrying `exp` and `jti`. This
is non-negotiable: the response is a list of staff mailboxes, and an unsigned
route would publish every client's admin email to anyone who guesses the path.
Expired or unsigned requests get 403.

Returns, per form found:

```json
{ "plugin": "elementor",
  "name": "New Form",
  "id_prefix": "",
  "recipients": ["website@digilatics.com"] }
```

Readers, each guarded by a `class_exists`/`post_type_exists` check so the route
degrades to an empty list rather than a fatal on a site without that plugin:

| Plugin | Where it reads | Join key it returns |
|---|---|---|
| Elementor Pro | `_elementor_data` post meta, `form` widgets with an `email` action | `name` (Elementor renders `<form name="...">`) |
| Contact Form 7 | `wpcf7_contact_form` posts, `_mail['recipient']` | `id_prefix` = `wpcf7-f{ID}-` |
| WPForms | `wpforms` posts, `settings.notifications.*.email` | `id_prefix` = `wpforms-form-{ID}` |
| Gravity Forms | `GFAPI::get_forms()` notifications | `id_prefix` = `gform_{ID}` |

Shortcode-carried overrides (`[contact-form-7 ... ]`, Elementor's per-page
duplicates) are out of scope: the stored form config is what the site will use
in the overwhelming majority of cases, and a wrong-but-plausible address is worse
than none.

Values run through `sanitize_email` and non-addresses are dropped. WordPress
placeholders (`[admin_email]`, `{site_email}`) resolve where trivially possible
and are otherwise skipped.

### 2. `websites.fetch_wp_form_recipients` Celery task

Per website with a `wp_sso_secret` and at least one `DetectedForm`. Mints a
2-minute signed token, `assert_public_url`s the target (SSRF guard, as `scan`
does), GETs the route with a short timeout, and matches each returned entry to
that website's forms:

- `name` → `form_name` exact match
- `id_prefix` → `form_id__startswith`

A match sets `recipient_email` to the first recipient and `recipient_source` to
`wordpress`. Unmatched entries are logged and ignored — a form configured in WP
that no visitor has loaded yet has no row to fill.

Scheduled daily (06:45 UTC, after the health recalculation) and triggerable
per-website from the Setup tab so the agency doesn't wait a day after pasting.

Failures are non-fatal and quiet: a site that never pasted the snippet returns
404 on every run, and that must not fill the logs with errors or mark the site
unhealthy.

### 3. `DetectedForm.recipient_source`

New field, choices `""` (unknown) / `page` / `wordpress`. Two jobs:

- **Precedence.** WordPress is the actual configuration; the page is a proxy for
  it. `_upsert_form` must not overwrite a `wordpress` value with what it read
  from the markup.
- **Honesty in the UI.** "Read from the page markup" and "Read from WordPress"
  are different claims with different reliability, and the detail dialog already
  explains which is which.

`_upsert_form` currently writes `recipient_email` unconditionally through
`update_or_create(defaults=...)`, which would wipe every WordPress-sourced address
on the next pageview. It changes to: write only when the page actually reported an
address **and** the stored source isn't `wordpress`. An empty page reading leaves
the stored value alone rather than clearing it — one observation of a form is not
proof its `mailto:` is gone, the same reasoning the diff window already applies to
scripts.

`compute_fingerprint` does not include the recipient, so none of this mints new
rows.

### 4. Frontend

`DetectedForm` gains `recipient_source`. The detail dialog's destination block
already branches on "have an address" vs "don't"; it gains a third case:

- `wordpress` → "Read from this site's WordPress configuration."
- `page` → the existing markup explanation.
- neither, and no address → the existing "set server-side" explanation, minus the
  WordPress plugin list once WP Connect is reporting for that site, since at that
  point the honest message is "WordPress didn't report a recipient for this form".

## Testing

- `normalize_recipient_email` already covered; extend for the WP payload shape.
- Task: matches by name; matches by id prefix; leaves unmatched rows alone;
  survives 404 / timeout / malformed JSON without raising; refuses a website with
  no secret.
- `_upsert_form`: a page ingest does not clear a `wordpress` recipient; a page
  recipient still fills a blank row; a `wordpress` recipient outranks a `page` one.
- Signature: an unsigned or expired request is rejected (asserted against the
  Python signer, since the PHP side isn't executed in tests).

The PHP itself is not unit-tested — it isn't executed in CI. Its readers are
plain post-meta lookups, and the route is guarded so a missing plugin returns an
empty list.

## Out of scope

- Alerting on a recipient change. Worth having, and cheap once the field is
  trustworthy, but it needs its own change-record and cooldown decisions and
  belongs in a follow-up.
- Cc/Bcc, and forms whose routing is conditional on field values.
- Non-WordPress platforms. They keep showing "Server-side".
