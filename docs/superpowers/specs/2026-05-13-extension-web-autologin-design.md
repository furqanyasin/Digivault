# Extension Web Auto-Login & Popup Auth Status — Design Spec

**Date:** 2026-05-13
**Status:** Approved

---

## Overview

Two related improvements to the Digivault Chrome extension:

1. **Auto-login**: When a user visits `digivault.digilatics.co/login` and is already authenticated in the extension, automatically log them into the web app and redirect to `/dashboard` — no password re-entry.

2. **Popup auth status**: When the extension popup is opened on the Digivault domain, show the user's extension auth state (logged in as X / not logged in) instead of the unhelpful "This site is not registered with Digivault." message.

---

## Context

- The frontend uses **HttpOnly cookies** (`ss_access`, `ss_refresh`) set by Next.js API routes — JavaScript cannot set or read these directly.
- The extension stores its own JWT pair in `chrome.storage.local` (`access`, `refresh`, `email`).
- These are the same tokens issued by the same Django backend, so they are valid credentials for the web session.
- Because cookies are HttpOnly, the only way to bridge extension tokens → web session is through a server-side exchange.

---

## Feature 1: Auto-Login

### Flow

```
content.js detects hostname === "digivault.digilatics.co" AND pathname starts with "/login"
  │
  ├─ sendMessage WEB_HANDOFF to background.js
  │
background.js
  ├─ reads access token from chrome.storage.local
  ├─ if no token → reply { skip: true } (user not logged into extension; do nothing)
  ├─ POST /api/extension/web-handoff/  (Bearer: access token)
  │     Django: verify JWT → generate UUID one-time code
  │             store in Redis: key="ext_handoff:<code>" value={access,refresh} TTL=60s
  │             return { code: "<uuid>" }
  ├─ reply { code: "<uuid>" } to content.js
  │
content.js
  └─ window.location.replace("/auth/extension?code=<uuid>")

Next.js /auth/extension page (new)
  └─ on mount: fetch /api/auth/ext-handoff?code=<uuid>

Next.js /api/auth/ext-handoff route (new)
  ├─ GET /api/extension/exchange/?code=<uuid>  (no auth required — code is the credential)
  │     Django: look up Redis key, return {access, refresh}, DELETE the key (one-time use)
  ├─ set ss_access cookie (httpOnly, same config as /api/auth/login)
  ├─ set ss_refresh cookie (httpOnly, same config as /api/auth/login)
  └─ return { ok: true }  → page redirects to /dashboard
```

### Error cases

| Scenario | Behaviour |
|---|---|
| Extension not logged in | content.js skips — login page shown normally |
| `web-handoff` returns 401 (expired/invalid JWT) | background tries refresh first; if that fails, skips |
| Code already used or expired (60s) | `/exchange/` returns 404; frontend redirects to `/login` with `?error=session_expired` |
| User is already logged into web app | content.js checks for existing `ss_access` cookie presence via a HEAD request to `/api/auth/me` before triggering the flow; if 200 → redirect to `/dashboard` directly |

### Django changes

**New endpoint: `POST /api/extension/web-handoff/`**
- Auth: JWT Bearer (same as all other extension endpoints)
- Generates `uuid4()` as one-time code
- Stores in Redis: `ext_handoff:<code>` → `json.dumps({access, refresh})`, TTL 60 seconds
- Returns `{"data": {"code": "<uuid>"}, "errors": [], "meta": {}}`

**New endpoint: `GET /api/extension/exchange/?code=<code>`**
- Auth: none (the code is the credential)
- Throttle: 10/minute anon
- Looks up `ext_handoff:<code>` in Redis
- If missing/expired → 404
- Returns `{"data": {"access": "...", "refresh": "..."}, "errors": [], "meta": {}}`
- Deletes the Redis key immediately after read (one-time use)

Both endpoints live in `apps/credentials/extension_urls.py` (already mounted at `/api/extension/`).

### Frontend changes

**New page: `frontend/src/app/(auth)/auth/extension/page.tsx`**
- Client component, runs on mount
- Reads `code` from `useSearchParams()`
- Calls `fetch("/api/auth/ext-handoff?code=<code>")`
- On success → `router.replace("/dashboard")`
- On error → `router.replace("/login?error=session_expired")`
- Shows a brief "Signing you in…" loading state

**New API route: `frontend/src/app/api/auth/ext-handoff/route.ts`**
- `GET` handler, reads `code` from `searchParams`
- Calls `GET ${API_BASE}/api/extension/exchange/?code=<code>`
- On 404 → returns `{ detail: "Invalid or expired link" }` status 400
- On success → sets `ss_access` + `ss_refresh` cookies (identical config to `/api/auth/login`) and returns `{ ok: true }`

### Extension changes

**`background.js` — new `WEB_HANDOFF` message handler**
```
handleWebHandoff()
  1. getToken() — if null, return { skip: true }
  2. POST /api/extension/web-handoff/ with Bearer token
  3. If 401 → tryRefreshToken() → retry once
  4. If still failing → return { skip: true }
  5. Return { code: "<uuid>" }
```

**`content.js` — login page detection**
- At the end of `run()`, after the existing credential autofill logic:
- Check: `location.hostname === <SCDB_HOST> && location.pathname.startsWith("/login")`
- `SCDB_HOST` is read from the same `getApiBase()` value (parsed from the stored serverUrl) so it works in dev too
- `safeSendMessage({ type: "WEB_HANDOFF" }, ...)` → on `{ code }` reply: `window.location.replace("/auth/extension?code=" + code)`
- Guard: only fires once per page load (use a module-level flag `let handoffAttempted = false`)

---

## Feature 2: Popup Auth Status

When the popup opens on the Digivault domain (`hostname === SCDB_HOST`), show the extension's auth state instead of the "not registered" fallback.

### popup.js changes

After receiving `GET_DATA` response, check if the current tab's hostname matches `SCDB_HOST`. If it does:
1. Read `{ access, email }` from `chrome.storage.local`
2. Render an auth status panel:
   - **Logged in**: "Signed in as [email]" + "Open Dashboard →" link + "Sign out" button
   - **Not logged in**: "Sign in to Digivault to enable autofill." + "Open Settings" button (opens options page)

### popup.html changes

Add a hidden `<div id="scdb-auth">` section with the two state templates (shown/hidden via JS).

---

## Security notes

- One-time codes are UUID v4 (122 bits entropy), 60-second TTL, deleted on first use — replay is not possible.
- The `/exchange/` endpoint returns tokens only once; a second request with the same code returns 404.
- The extension only triggers the flow when already authenticated (valid JWT required to call `/web-handoff/`).
- No tokens are written to localStorage or the URL bar for more than the single navigation.

---

## Files changed

| File | Change |
|---|---|
| `apps/credentials/extension_urls.py` | Add two new URL patterns |
| `apps/credentials/views.py` | Add `WebHandoffView`, `WebHandoffExchangeView` |
| `extension/background.js` | Add `WEB_HANDOFF` handler + `handleWebHandoff()` |
| `extension/content.js` | Add login-page detection + handoff trigger |
| `extension/popup/popup.js` | Add Digivault-domain auth status rendering |
| `extension/popup/popup.html` | Add `#scdb-auth` section |
| `frontend/src/app/(auth)/auth/extension/page.tsx` | New page |
| `frontend/src/app/api/auth/ext-handoff/route.ts` | New API route |
