# Granular Credential Sharing (LastPass-style) — Design

**Date:** 2026-06-10
**Status:** Approved, implementing

## Problem

Credentials should not all be visible to everyone. Owners/Managers (and a
credential's creator) see and manage everything; Developers should see only the
specific credentials shared with them. Sharing should be per-credential, with an
optional site-level "share all credentials of this website" convenience, and a
per-share toggle for whether the recipient may view the plaintext password.

## What already exists

The backend already implements most of this:
- `CredentialShare(credential, user, shared_by)` — per-credential grant, unique
  per (credential, user).
- `Credential.objects.visible_to(user)` — Owners/Managers see all team
  credentials; creators see their own; everyone else sees only shares.
- `GET/POST /api/v1/credentials/<pk>/shares/` and
  `DELETE .../shares/<user_id>/`, gated by `can_modify_credential`
  (Owner/Manager/creator). Audit logged.
- Team-member list endpoint for the recipient picker.

The frontend "Share" button today only copies the credential to the clipboard —
it does not use these endpoints.

## Changes

### Backend
- Add `can_view_password = BooleanField(default=True)` to `CredentialShare`.
- `CredentialShareWriteSerializer` accepts `can_view_password` (default `True`);
  the POST upserts shares with `update_or_create` so re-sharing updates the flag.
- `CredentialShareSerializer` exposes `can_view_password`.
- **Reveal enforcement** — a user's effective password access is `True` for
  Owner/Manager/creator, else their share's `can_view_password`.
  `CredentialService.reveal(..., for_autofill=False)`: when effective access is
  `False` and `for_autofill` is `False`, the returned `password` is blanked and
  `password_hidden=True`. `CredentialRevealView` reads `for_autofill` from the
  request so the extension can still autofill.
- **Site-level share** — `POST /api/v1/websites/<website_pk>/credentials/share/`
  with `{user_ids, can_view_password}` fans the grant out across every
  credential of that website the requester may modify.

### Frontend
- New proxy routes: `/api/credentials/[id]/shares` (GET/POST),
  `/api/credentials/[id]/shares/[userId]` (DELETE),
  `/api/websites/[id]/credentials/share` (POST).
- Rebuild the share modal to match the LastPass-style screen: recipient picker
  (team Developers), "Allow Recipient to View Password" checkbox, "Existing
  Shares" list with revoke. Wire to the real endpoints.
- Reveal UI: when `password_hidden`, show username/notes but hide the password.
- Card favicons: show the site favicon on each vault card, falling back to the
  lock icon.

### Extension
- Autofill reveals with `?for_autofill=1` so no-password shares still autofill.

## Honest limitation

"Allow Recipient to View Password = off" is a workflow guardrail, not a
cryptographic boundary. Autofill must place the real password into the page to
fill the login form, so a technically-savvy developer could extract an
autofilled password from the DOM. It reliably prevents casual viewing/copying
inside Digivault — which is what LastPass's "hide password" also does.

## Testing

- `can_view_password=False` share → dashboard reveal blanks password &
  sets `password_hidden`; `for_autofill=1` returns it.
- Owner/Manager/creator always get the password.
- Site-level share creates shares across all of a website's credentials.
- Re-sharing updates the flag (no duplicate rows).
