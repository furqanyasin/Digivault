# Reading form recipients over the WordPress REST API

**Date:** 2026-08-27
**Status:** Draft — awaiting review

## Problem

`apps/websites/wp_forms.py` answers "where does this form deliver?" correctly, but
only for sites that have pasted the WP Connect PHP snippet. Everywhere else the
Forms tab's "Goes to" column stays empty and `POST /api/websites/<id>/sync-form-recipients/`
returns 409 `"Set up WP Connect for this website first."`

The paste is the objection. An agency onboarding a client can add one tracking
script tag; asking for a second, PHP-shaped paste into WPCode is a separate
conversation with the client, and on many sites it never happens. We want the
recipient without it.

## The constraint, stated plainly

The recipient is not in the page and cannot be put there. It lives in
`wp_postmeta` (Elementor `_elementor_data`, CF7 `_mail`), in the form post's
`post_content` (WPForms), or in plugin-owned tables (`wp_gf_form_meta`). No
unauthenticated request returns any of it — not REST, not `admin-ajax.php`, not
the rendered HTML.

So **"just the script tag and nothing else" cannot work by any mechanism.**
Reading a private database value requires authorisation. The only open question
is which credential we present and what it can reach.

The cheapest credential is one we often already hold: `Credential` rows of type
`WORDPRESS` are linked per-website and Fernet-encrypted today. For those sites
this feature needs no new setup at all — no plugin, no snippet, no client
involvement.

## What a credential can actually reach

One WordPress core rule governs everything here. `map_meta_cap()` resolves
`edit_post_meta` as:

    $allowed = ! is_protected_meta( $meta_key, $object_type );

then lets an `auth_{$object_type}_meta_{$meta_key}` filter override it — the
filter that `register_meta()`'s `auth_callback` installs. Underscore-prefixed
meta is therefore invisible unless its plugin deliberately registered it. The
same rule gates REST `context=edit` **and** XML-RPC `custom_fields`
(`WP_XMLRPC_Server::get_custom_fields()` skips any key failing
`current_user_can( 'edit_post_meta', ... )`, under the comment "Don't expose
protected fields").

Checked against current plugin source rather than assumed:

| Plugin | Verdict | Evidence |
|---|---|---|
| **Elementor >= 3.27.0** | Reachable | `modules/wp-rest/classes/elementor-post-meta.php` registers `_elementor_data` with `show_in_rest` (context `edit`) and `auth_callback => check_edit_permission`. Registered unconditionally in `modules/wp-rest/module.php`; only `Design_System_REST_API` sits behind an experiment flag. File absent at tag 3.26.0, present at 3.27.0 — that is the version floor. |
| **Gravity Forms >= 2.4.21.4** | Reachable | Documented support for WordPress Application Passwords over Basic auth on REST v2; requests run with the authenticated user's Gravity capabilities. `GET /wp-json/gf/v2/forms/<id>` returns `notifications`. |
| **Contact Form 7** | Unreachable | Persists every property as `'_' . $prop` (`includes/contact-form.php:1283`), so `_mail` is protected meta, and the plugin contains **no `register_meta` call at all**. Its own REST controller returns `properties.form` and `properties.additional_settings` only — mail config is not in the response. |
| **WPForms** | Unreachable | CPT `wpforms` is registered `'public' => false` with no `show_in_rest` (`includes/class-form.php:110`). The Abilities API integration returns `get_safe_settings()`, an explicit allowlist — `form_title`, `form_desc`, `submit_text`, `ajax_submit`, `honeypot`, `antispam` — under the comment "Return only safe, non-sensitive settings". Notifications are excluded by design. |

**Coverage is Elementor and Gravity Forms. CF7 and WPForms remain WP-Connect-only.**
This feature narrows the set of sites that need the PHP paste; it does not
eliminate it. That limit is a decision by those two plugins, not something more
implementation effort can move.

Elementor's registration hooks `rest_api_init`, so `_elementor_data` is exposed
to REST requests and *not* to XML-RPC. Authenticated REST is consequently the
only transport worth building.

## Rejected alternatives

- **Harvest from the page when a logged-in admin visits.** The one way a script
  could do it: same-origin reads of wp-admin against the viewer's session. It
  fires only when an editor happens to browse the front end, needs per-plugin
  HTML scraping in the browser, and puts session-riding exfiltration code in a
  third-party script served to every visitor — the exact behaviour Digivault
  exists to alert its customers about.
- **XML-RPC `wp.getPost` as a universal lever.** Attractive because CF7,
  WPForms and Elementor all persist to `wp_posts`/`wp_postmeta`, so one call
  would cover three plugins. Dead on the protected-meta rule above, and dead
  again on Elementor registering only during `rest_api_init`.
- **Server-side form login to `wp-login.php` with a vaulted password.** Covers
  every plugin by scraping admin screens, because it holds a real session rather
  than an API credential. Rejected on the constraint in CLAUDE.md that all
  outbound traffic leaves from one IP: repeated automated logins trip Wordfence
  and Limit Login Attempts, and a ban costs us uptime monitoring for that client
  — a far more valuable signal than a recipient address.
- **Read it in the Chrome extension while the agency is in wp-admin.** Genuinely
  covers all four plugins and needs nothing on the client site. Rejected for
  *this* iteration only because it is operator-triggered rather than unattended,
  which is what was asked for. It stays the natural answer for CF7 and WPForms
  if their gap ever needs closing.

## Components

### 1. Credential storage

Add `CredentialType.WORDPRESS_APP_PASSWORD`. Reusing `Credential` rather than
adding a field to `Website` inherits Fernet encryption, team scoping, the
website FK, sharing, rotation tracking and the vault UI at no cost.

Resolution order per website, first usable wins:

1. a `WORDPRESS_APP_PASSWORD` credential linked to the website
2. a `WORDPRESS` credential linked to the website

Application Passwords are the documented path and should be preferred: they are
revocable independently of the human login, are capability-scoped, and a failed
Basic auth against them does not consume a login-lockout budget the way a real
password does.

### 2. Transport

Everything goes through `apps.common.outbound.fetch` — the per-host token
bucket, the honest user-agent, WAF fingerprinting and the per-redirect-hop SSRF
guard are all mandatory here, since these are authenticated requests to customer
origins.

Two changes it needs:

- **`read_bytes` must be raisable per call.** The default 65536 truncates
  `_elementor_data` on any real page and would silently yield a half-parsed JSON
  blob. The reader passes an explicit, larger cap and treats a response that
  hits the cap as a failure, never as "no recipient found".
- **Basic auth** rides in `extra_headers`; no new parameter required.

No request-body support is needed — every call is a GET.

### 3. Reader registry

New module `apps/websites/wp_api_forms.py`, deliberately a sibling of
`wp_forms.py` rather than an extension of it. Each reader is a small object
answering two questions: can I read this site, and what did I find. Every reader
returns the **existing entry shape** `wp_forms.apply_recipients()` already
consumes — `{plugin, name, id_prefix, to, cc, bcc}` — so `_match()`,
`_matches_prefix()` and `build_recipients()` are reused untouched.

Adding a reader later is then a self-contained change, which matters because the
CF7/WPForms verdicts above are properties of current plugin versions.

### 4. Elementor reader

Enumerate `pages`, `posts` and `elementor_library` via
`GET /wp-json/wp/v2/<type>?context=edit&_fields=id,link,meta&per_page=<n>`,
paginating on `X-WP-TotalPages`.

`per_page` must be small — each row carries a whole `_elementor_data` blob, so
the natural `per_page=100` produces multi-megabyte responses. Pick a modest page
size and stop after a bounded number of pages; log what was skipped rather than
truncating silently, per the no-silent-caps rule.

For each row, walk the `_elementor_data` JSON tree for elements with
`widgetType == "form"` and read the email action's recipient settings plus
`settings.form_name`. Elementor renders the form name into the form element's
`name` attribute, which is exactly the key `_match()`'s name fallback joins on.

The precise Elementor Pro settings keys (`email_to` and its Cc/Bcc siblings)
could not be verified from source — Elementor Pro is not publicly distributed.
The first implementation step is to dump one real site's `_elementor_data` and
read the keys off it. Everything else in this design is verified; this one
detail is not.

### 5. Gravity Forms reader

`GET /wp-json/gf/v2/forms` for the id list, then `GET /wp-json/gf/v2/forms/<id>`
per form, reading `notifications[].to`. Emit `id_prefix: "gform_<id>"`, which
`_matches_prefix()` already resolves correctly — its digit rule is what stops
`gform_1` claiming `gform_12`'s row.

Skip notifications whose `toType` is a field reference or routing rule rather
than a literal address: those resolve per submission and have no fixed
recipient. Recording the raw value would display a field id as an email.

### 6. Recipient precedence

Add `RecipientSource.WP_API`. Ranking becomes `page < wp_api < wordpress`.

WP Connect stays authoritative where it exists: it reads the database directly
through a signature-gated route, while this path reads what the REST API chooses
to expose.

`_apply_page_recipients()` in `apps/scripts/tasks.py` currently early-returns
only on `WORDPRESS`. It must early-return on `WP_API` too. Without that, every
pageview overwrites an API-sourced address with the markup's empty reading —
precisely the bug the WordPress guard was added to fix.

Transitions write a `record_recipient_change()` row like any other, so a client
repointing an Elementor form still surfaces as a change.

### 7. Scheduling and API

- A daily sweep beside the existing WP Connect one, over websites that have a
  usable credential.
- `sync_form_recipients` stops returning 409 when `wp_sso_secret` is absent: try
  WP Connect, then the API readers, and 409 only when neither is available. The
  message becomes actionable — add WordPress credentials, or set up WP Connect.
- Surface which source answered, so the Forms tab can distinguish "Server-side"
  from "read over the WP API" and a site with no path at all says so.

## Failure handling

Every failure is a normal state, matching `fetch_recipients()`: no raise, no
error-level log, no effect on the site's health score. Most sites will have no
credential; many will have Application Passwords unavailable, `Authorization`
stripped by the host, or REST disabled.

One addition. A credential that fails authentication must be **recorded and not
retried nightly forever** — repeated 401s from a single IP are what gets that IP
banned, and the ban costs us monitoring. Persist the failure, surface it in the
UI as "credentials rejected", and require a credential edit to re-arm.

Automated reads should leave an audit trail, but `CredentialAccessLog.user` is a
non-nullable FK and a scheduled sweep has no user. Resolve deliberately: either
make that column nullable, or record system reads elsewhere. Do not quietly skip
the audit — this is a product whose selling point is credential hygiene.

## Testing

Per `tests/conftest.py` conventions: the autouse `no_network_in_tests` fixture
covers Website-creation checks only, so every `outbound.fetch` here needs its
own mock. Run `pytest --create-db` after the migrations.

- Reader unit tests on captured fixture payloads: a real `_elementor_data` tree,
  a Gravity form with a literal `to`, and one with a field-reference `toType`.
- Precedence: an ingest with empty markup must not clear a `wp_api` recipient;
  a WP Connect answer must override one; a `wp_api` answer must override `page`.
- Matching: Gravity `gform_1` must not claim `gform_12`; an Elementor form must
  join by name.
- Failure paths: 401, 403 behind a WAF, REST disabled, a response that hits the
  byte cap — each must leave stored recipients untouched.
- The truncation case deserves its own test. It is the one failure that could
  write a wrong answer rather than no answer.

## Limits, stated for the record

- CF7 and WPForms are not covered and will keep asking for WP Connect.
- Elementor below 3.27.0 is not covered.
- Sites with no vaulted WordPress credential are not covered.
- Elementor Cc/Bcc support depends on settings keys not yet verified.
- A site whose host strips the `Authorization` header cannot be read even with
  correct credentials, and cannot be distinguished from a wrong password without
  inspecting the response body.
