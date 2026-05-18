# Extension Password Manager — Design Spec

**Date:** 2026-05-12
**Status:** Approved

---

## Overview

Add LastPass-style autofill to the Digivault Chrome extension. When a user visits a page with a login form, the extension detects it, looks up saved credentials from the Digivault dashboard, and injects an icon inside the username field. Clicking the icon shows a dropdown of matching credentials; selecting one reveals and fills both fields.

The backend already has a full `credentials` app with Fernet AES-256 encryption, a reveal endpoint, and audit logging. This feature adds one new API endpoint and extends the extension (no new Django app needed).

---

## Architecture

```
Options page
  └─ Login form → POST /api/v1/auth/token/ → stores {access, refresh} in chrome.storage.local

content.js (injected into every page)
  └─ Detects input[type=password] + nearest username field
  └─ Sends GET_CREDENTIALS to background
  └─ If credentials returned → injects icon inside username field
  └─ Icon click → shows credential dropdown
  └─ Credential selected → sends REVEAL_CREDENTIAL to background
  └─ Fills username + password fields with revealed plaintext

background.js (service worker)
  ├─ GET_CREDENTIALS → GET /api/extension/credentials/?domain=<domain>
  ├─ REVEAL_CREDENTIAL → POST /api/v1/credentials/<id>/reveal/
  └─ Auto-refreshes JWT on 401 using stored refresh token

Backend (one new endpoint)
  └─ GET /api/extension/credentials/?domain=<domain>
     Authenticated. Returns [{id, label, credential_type, login_url}].
     Never returns plaintext.
```

---

## Backend Changes

### New endpoint: `GET /api/extension/credentials/`

**URL:** `/api/extension/credentials/?domain=<domain>`
**Auth:** JWT Bearer token (same as all other v1 endpoints)
**Permission:** `IsAuthenticated` + `IsTeamMember`

Logic:
1. Extract `domain` from query param.
2. Find all `Website` objects belonging to the user's active team whose `domain` field matches (exact, case-insensitive).
3. Return all `Credential` objects for those websites — metadata only, no plaintext.

Response shape:
```json
[
  {
    "id": "uuid",
    "label": "WordPress Admin",
    "credential_type": "wordpress",
    "login_url": "https://example.com/wp-admin"
  }
]
```

Returns `[]` (not 404) when no credentials are found — the extension treats this as "nothing to offer".

**File locations:**
- View: `apps/credentials/views.py` — new `ExtensionCredentialLookupView`
- URL: new `apps/credentials/extension_urls.py` — single path `credentials/`
- Mount: `config/urls.py` — add `path("api/extension/", include("apps.credentials.extension_urls"))`
- Serializer: `apps/credentials/serializers.py` — reuse `CredentialSerializer` (already has these fields, no plaintext)

No new model or migration needed.

---

## Extension Changes

### 1. Options page — Login section

Add a login form above the existing server URL field:

- Email input + password input + Login button
- On submit: POST `{email, password}` to `<serverUrl>/api/v1/auth/token/`
- On success: store `{access, refresh, email}` in `chrome.storage.local`
- Show logged-in state: "Logged in as user@example.com" with a Logout button
- Logout: clears token from storage

Token storage: `chrome.storage.local` (persists across browser restarts, not synced across devices — appropriate for auth tokens).

### 2. background.js — Two new message handlers

**`GET_CREDENTIALS`**
- Input: `{domain}`
- Reads `access` token from `chrome.storage.local`
- If no token: reply `{error: "not_authenticated"}`
- GET `<serverUrl>/api/extension/credentials/?domain=<domain>`
- On 401: attempt token refresh via `/api/v1/auth/token/refresh/`, retry once
- Reply with credential array (or `[]`)

**`REVEAL_CREDENTIAL`**
- Input: `{credentialId}`
- POST `<serverUrl>/api/v1/credentials/<id>/reveal/` with Bearer token
- On 401: attempt token refresh, retry once
- Reply with `{username, password}` plaintext (only in-memory, never stored)

Token refresh helper: shared by both handlers — if refresh fails, clears stored tokens and replies `{error: "session_expired"}`.

### 3. content.js — Login form detection and autofill UI

**Detection (runs once on `document_idle`):**
1. Find all `input[type=password]` on the page.
2. For each, locate the nearest preceding `input` with `type` of `text`, `email`, or no type (username heuristic).
3. If at least one username+password pair found, send `GET_CREDENTIALS` with `location.hostname`.
4. If response is empty or error, do nothing — no UI injected.

**Icon injection:**
- For each username field with matching credentials, wrap the field in a `position: relative` container (if not already), inject a `<button>` absolutely positioned at the right edge (16×16px, Digivault icon SVG).
- The button has `z-index: 2147483647` and `pointer-events: all`.
- Clicking the button toggles a credential dropdown.

**Credential dropdown:**
- A `<div>` positioned below the username field, `max-height: 200px`, scrollable.
- Lists each credential as `<button>`: `label` on the left, `credential_type` chip on the right.
- Keyboard navigable (arrow keys, Enter, Escape).
- Clicking a credential: sends `REVEAL_CREDENTIAL` to background → on reply, fills username field value + dispatches `input`/`change` events, then fills the paired password field the same way.
- Closes the dropdown after fill.

**Cleanup:** If the page navigates (SPA), a `MutationObserver` re-runs detection when the DOM changes significantly.

**Style isolation:** All injected elements use a Shadow DOM root to prevent the host page's CSS from bleeding in.

---

## Security

| Concern | Mitigation |
|---|---|
| Token storage | `chrome.storage.local` — not accessible to page JS, not synced |
| Plaintext in memory | Revealed password lives only in the content script message handler, filled immediately, not stored |
| XSS via credential data | Label/type rendered as `textContent`, not `innerHTML` |
| CSRF | JWT Bearer auth — no cookies, no CSRF surface |
| Audit trail | Every reveal call hits the existing `CredentialRevealView` which writes a `CredentialAccessLog` row |
| Icon injection on sensitive pages | Detection only runs on pages with an actual `input[type=password]` — no UI injected otherwise |

---

## Out of Scope

- Saving new credentials from the extension (dashboard-only)
- Generating passwords
- Firefox support (MV3 compatibility can be added later)
- Syncing tokens across devices

---

## Files Changed

**Backend:**
- `apps/credentials/views.py` — add `ExtensionCredentialLookupView`
- `apps/credentials/extension_urls.py` — new file, single route
- `config/urls.py` — add `path("api/extension/", include("apps.credentials.extension_urls"))`

**Extension:**
- `extension/background.js` — add `GET_CREDENTIALS`, `REVEAL_CREDENTIAL` handlers + token refresh
- `extension/content.js` — replace with full login-form detection + Shadow DOM injection
- `extension/options/options.html` — add login section
- `extension/options/options.js` — add login/logout logic
- `extension/manifest.json` — no changes needed (permissions already sufficient)
