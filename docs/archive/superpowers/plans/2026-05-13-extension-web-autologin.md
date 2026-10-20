# Extension Web Auto-Login & Popup Auth Status — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user is logged into the extension and visits the Digivault login page, automatically log them into the web app and redirect to `/dashboard`; also show auth status in the popup when on the Digivault domain.

**Architecture:** Extension detects the login page, calls a new backend endpoint to exchange its JWT for a short-lived one-time code stored in Redis, then navigates the browser tab to a new Next.js handoff page that exchanges the code for HttpOnly session cookies. The popup separately reads extension storage to show auth state when on the Digivault domain.

**Tech Stack:** Django + django-redis cache, simplejwt token generation, Next.js App Router API routes, Chrome Extension MV3 content/background scripts.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `apps/credentials/views.py` | Modify | Add `WebHandoffView`, `WebHandoffExchangeView` |
| `apps/credentials/extension_urls.py` | Modify | Register two new URL patterns |
| `tests/credentials/test_extension_web_handoff.py` | Create | Tests for both new Django endpoints |
| `frontend/src/app/api/auth/ext-handoff/route.ts` | Create | Next.js API route — exchanges OTT for cookies |
| `frontend/src/app/(auth)/auth/extension/page.tsx` | Create | Landing page that triggers the exchange and redirects |
| `extension/background.js` | Modify | Add `WEB_HANDOFF` message handler |
| `extension/content.js` | Modify | Detect login page, trigger handoff, navigate tab |
| `extension/popup/popup.html` | Modify | Add `#scdb-auth` section |
| `extension/popup/popup.js` | Modify | Render auth status when on Digivault domain |

---

## Task 1: Django — `POST /api/extension/web-handoff/`

**Files:**
- Modify: `apps/credentials/views.py`
- Modify: `apps/credentials/extension_urls.py`

This endpoint is called by the extension's background worker. It verifies the user's JWT (already handled by DRF authentication), generates fresh tokens for that user, stores them in Redis under a UUID one-time code with a 60-second TTL, and returns the code.

- [ ] **Step 1: Add `WebHandoffView` to views.py**

Open `apps/credentials/views.py`. Add these imports at the top alongside the existing ones:

```python
import uuid
from django.core.cache import cache
from rest_framework_simplejwt.tokens import RefreshToken
```

Then add this class at the bottom of the file:

```python
class WebHandoffView(APIView):
    """POST /api/extension/web-handoff/

    Issues a short-lived one-time code (60 s, stored in Redis) that the
    Next.js /auth/extension page can exchange for HttpOnly session cookies.
    Requires a valid extension JWT — the code is bound to the authenticated user.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh = RefreshToken.for_user(request.user)
        code = uuid.uuid4().hex
        cache.set(
            f"ext_handoff:{code}",
            {"access": str(refresh.access_token), "refresh": str(refresh)},
            timeout=60,
        )
        return Response({"code": code})
```

- [ ] **Step 2: Add `WebHandoffExchangeView` to views.py**

Add this class immediately after `WebHandoffView`:

```python
class WebHandoffExchangeView(APIView):
    """GET /api/extension/exchange/?code=<code>

    One-time exchange: returns the access + refresh tokens stored under the
    given code and immediately deletes the cache key (replay not possible).
    No authentication required — the code itself is the credential.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        code = request.query_params.get("code", "").strip()
        if not code:
            return Response(
                {"detail": "code parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        key = f"ext_handoff:{code}"
        tokens = cache.get(key)
        if tokens is None:
            return Response(
                {"detail": "Invalid or expired code"},
                status=status.HTTP_404_NOT_FOUND,
            )
        cache.delete(key)
        return Response(tokens)
```

- [ ] **Step 3: Register the two new URL patterns**

Open `apps/credentials/extension_urls.py`. Add the two new views to the import and add two paths:

```python
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.credentials.views import (
    ExtensionCredentialLookupView,
    WebHandoffView,
    WebHandoffExchangeView,
)

urlpatterns = [
    path("token/", TokenObtainPairView.as_view(), name="extension-token"),
    path("token/refresh/", TokenRefreshView.as_view(), name="extension-token-refresh"),
    path("credentials/", ExtensionCredentialLookupView.as_view(), name="extension-credentials"),
    path("web-handoff/", WebHandoffView.as_view(), name="extension-web-handoff"),
    path("exchange/", WebHandoffExchangeView.as_view(), name="extension-exchange"),
]
```

- [ ] **Step 4: Commit**

```bash
git add apps/credentials/views.py apps/credentials/extension_urls.py
git commit -m "feat: add web-handoff and exchange endpoints for extension auto-login"
```

---

## Task 2: Django — Tests for handoff endpoints

**Files:**
- Create: `tests/credentials/test_extension_web_handoff.py`

- [ ] **Step 1: Write failing tests**

Create `tests/credentials/test_extension_web_handoff.py`:

```python
import json
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="handoff@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Handoff Agency", owner=owner)


def _auth_client(user):
    client = APIClient()
    resp = client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "Pass123!"},
        format="json",
    )
    token = json.loads(resp.content)["data"]["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
class TestWebHandoff:
    def test_unauthenticated_returns_401(self):
        resp = APIClient().post("/api/extension/web-handoff/")
        assert resp.status_code == 401

    def test_returns_code_for_authenticated_user(self, owner, team):
        resp = _auth_client(owner).post("/api/extension/web-handoff/")
        assert resp.status_code == 200
        body = json.loads(resp.content)
        assert "code" in body["data"]
        assert len(body["data"]["code"]) == 32  # uuid4 hex

    def test_code_stored_in_cache(self, owner, team):
        resp = _auth_client(owner).post("/api/extension/web-handoff/")
        code = json.loads(resp.content)["data"]["code"]
        stored = cache.get(f"ext_handoff:{code}")
        assert stored is not None
        assert "access" in stored
        assert "refresh" in stored


@pytest.mark.django_db
class TestWebHandoffExchange:
    def test_missing_code_returns_400(self):
        resp = APIClient().get("/api/extension/exchange/")
        assert resp.status_code == 400

    def test_unknown_code_returns_404(self):
        resp = APIClient().get("/api/extension/exchange/", {"code": "doesnotexist"})
        assert resp.status_code == 404

    def test_valid_code_returns_tokens(self, owner, team):
        handoff_resp = _auth_client(owner).post("/api/extension/web-handoff/")
        code = json.loads(handoff_resp.content)["data"]["code"]

        exchange_resp = APIClient().get("/api/extension/exchange/", {"code": code})
        assert exchange_resp.status_code == 200
        body = json.loads(exchange_resp.content)["data"]
        assert "access" in body
        assert "refresh" in body

    def test_code_deleted_after_exchange(self, owner, team):
        handoff_resp = _auth_client(owner).post("/api/extension/web-handoff/")
        code = json.loads(handoff_resp.content)["data"]["code"]

        APIClient().get("/api/extension/exchange/", {"code": code})
        # Second request must fail
        second = APIClient().get("/api/extension/exchange/", {"code": code})
        assert second.status_code == 404

    def test_no_auth_required_for_exchange(self, owner, team):
        handoff_resp = _auth_client(owner).post("/api/extension/web-handoff/")
        code = json.loads(handoff_resp.content)["data"]["code"]
        # Unauthenticated client can exchange
        resp = APIClient().get("/api/extension/exchange/", {"code": code})
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/credentials/test_extension_web_handoff.py -v
```

Expected: all tests fail with `ImportError` or `404` (endpoints don't exist yet — but they do after Task 1, so if running in order these should pass).

- [ ] **Step 3: Run tests — expect all pass**

```bash
pytest tests/credentials/test_extension_web_handoff.py -v
```

Expected output — all 8 tests pass:
```
PASSED tests/credentials/test_extension_web_handoff.py::TestWebHandoff::test_unauthenticated_returns_401
PASSED tests/credentials/test_extension_web_handoff.py::TestWebHandoff::test_returns_code_for_authenticated_user
PASSED tests/credentials/test_extension_web_handoff.py::TestWebHandoff::test_code_stored_in_cache
PASSED tests/credentials/test_extension_web_handoff.py::TestWebHandoffExchange::test_missing_code_returns_400
PASSED tests/credentials/test_extension_web_handoff.py::TestWebHandoffExchange::test_unknown_code_returns_404
PASSED tests/credentials/test_extension_web_handoff.py::TestWebHandoffExchange::test_valid_code_returns_tokens
PASSED tests/credentials/test_extension_web_handoff.py::TestWebHandoffExchange::test_code_deleted_after_exchange
PASSED tests/credentials/test_extension_web_handoff.py::TestWebHandoffExchange::test_no_auth_required_for_exchange
```

- [ ] **Step 4: Run full credential test suite — no regressions**

```bash
pytest tests/credentials/ -v
```

Expected: all existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add tests/credentials/test_extension_web_handoff.py
git commit -m "test: add tests for web-handoff and exchange endpoints"
```

---

## Task 3: Frontend — `/api/auth/ext-handoff` API route

**Files:**
- Create: `frontend/src/app/api/auth/ext-handoff/route.ts`

This Next.js API route is called by the frontend handoff page. It contacts the Django exchange endpoint, then sets the same HttpOnly cookies that the normal login route sets.

- [ ] **Step 1: Create the route file**

Create `frontend/src/app/api/auth/ext-handoff/route.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get("code") ?? "";
  if (!code) {
    return NextResponse.json({ detail: "Missing code" }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_BASE}/api/extension/exchange/?code=${encodeURIComponent(code)}`
    );
  } catch {
    return NextResponse.json({ detail: "Cannot reach backend" }, { status: 502 });
  }

  if (!upstream.ok) {
    return NextResponse.json(
      { detail: "Invalid or expired link" },
      { status: 400 }
    );
  }

  let envelope: { data?: { access: string; refresh: string } };
  try {
    envelope = await upstream.json();
  } catch {
    return NextResponse.json({ detail: "Backend returned invalid response" }, { status: 502 });
  }

  const tokens = envelope.data!;
  const res = NextResponse.json({ ok: true });

  res.cookies.set("ss_access", tokens.access, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 5,
  });
  res.cookies.set("ss_refresh", tokens.refresh, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });

  return res;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/api/auth/ext-handoff/route.ts
git commit -m "feat: add ext-handoff API route for extension auto-login cookie exchange"
```

---

## Task 4: Frontend — `/auth/extension` landing page

**Files:**
- Create: `frontend/src/app/(auth)/auth/extension/page.tsx`

This page is navigated to by the extension. On mount it calls the `ext-handoff` route, sets cookies, and redirects. The user sees a brief "Signing you in…" message.

- [ ] **Step 1: Create the page**

Create `frontend/src/app/(auth)/auth/extension/page.tsx`:

```tsx
"use client";

import { useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function ExtensionHandoffPage() {
  const router = useRouter();
  const params = useSearchParams();
  const attempted = useRef(false);

  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;

    const code = params.get("code");
    if (!code) {
      router.replace("/login?error=missing_code");
      return;
    }

    fetch(`/api/auth/ext-handoff?code=${encodeURIComponent(code)}`)
      .then((res) => {
        if (res.ok) {
          router.replace("/dashboard");
        } else {
          router.replace("/login?error=session_expired");
        }
      })
      .catch(() => {
        router.replace("/login?error=session_expired");
      });
  }, [params, router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/40">
      <p className="text-muted-foreground text-sm">Signing you in…</p>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add "frontend/src/app/(auth)/auth/extension/page.tsx"
git commit -m "feat: add extension handoff landing page"
```

---

## Task 5: Extension background.js — `WEB_HANDOFF` message handler

**Files:**
- Modify: `extension/background.js`

- [ ] **Step 1: Add `handleWebHandoff` function**

Open `extension/background.js`. Add this function after `handleLogin` (around line 171):

```javascript
async function handleWebHandoff() {
  try {
    const apiBase = await getApiBase();
    let token = await getToken();
    if (!token) return { skip: true };

    const doHandoff = (t) =>
      fetch(`${apiBase}/api/extension/web-handoff/`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${t}`,
          "Content-Type": "application/json",
        },
      });

    let res = await doHandoff(token);
    if (res.status === 401) {
      const refreshed = await tryRefreshToken(apiBase);
      if (!refreshed) return { skip: true };
      res = await doHandoff(refreshed);
    }
    if (!res.ok) return { skip: true };

    const json = await res.json();
    const code = json.data?.code ?? json.code;
    if (!code) return { skip: true };
    return { code };
  } catch {
    return { skip: true };
  }
}
```

- [ ] **Step 2: Register the message handler**

In the `chrome.runtime.onMessage.addListener` block, add a new `if` branch after the `LOGIN` handler:

```javascript
  if (msg.type === "WEB_HANDOFF") {
    handleWebHandoff().then(reply);
    return true;
  }
```

- [ ] **Step 3: Commit**

```bash
git add extension/background.js
git commit -m "feat: add WEB_HANDOFF message handler to extension background"
```

---

## Task 6: Extension content.js — login page detection and handoff trigger

**Files:**
- Modify: `extension/content.js`

- [ ] **Step 1: Add module-level handoff flag and detection logic**

Open `extension/content.js`. After the line `let activeDropdown = null;` (around line 164), add:

```javascript
  let handoffAttempted = false;
```

Then at the very bottom of the IIFE, just before the closing `})();`, add the following block after the existing snippet ingest logic:

```javascript
  // ----------------------------------------------------------------
  // Extension auto-login on the Digivault web app login page
  // ----------------------------------------------------------------

  (async function maybeHandoff() {
    if (handoffAttempted) return;

    // Resolve the configured server hostname so dev + prod both work.
    const { serverUrl } = await new Promise((resolve) =>
      chrome.storage.sync.get("serverUrl", resolve)
    );
    const scdbHost = new URL(
      (serverUrl || "https://digivault.digilatics.co").replace(/\/$/, "")
    ).hostname;

    if (
      location.hostname !== scdbHost ||
      !location.pathname.startsWith("/login")
    ) return;

    handoffAttempted = true;

    safeSendMessage({ type: "WEB_HANDOFF" }, (result) => {
      if (!result || result.skip || !result.code) return;
      window.location.replace(
        `/auth/extension?code=${encodeURIComponent(result.code)}`
      );
    });
  })();
```

- [ ] **Step 2: Commit**

```bash
git add extension/content.js
git commit -m "feat: detect Digivault login page and trigger extension auto-login handoff"
```

---

## Task 7: Extension popup — auth status on Digivault domain

**Files:**
- Modify: `extension/popup/popup.html`
- Modify: `extension/popup/popup.js`

When the popup is opened on the Digivault domain, show the user's extension auth state instead of "This site is not registered."

- [ ] **Step 1: Add the auth status section to popup.html**

Open `extension/popup/popup.html`. Replace the entire `<main>` block with:

```html
  <main id="root" aria-live="polite">
    <p class="muted loading">Loading…</p>
  </main>
  <div id="scdb-auth" style="display:none" aria-live="polite"></div>
```

- [ ] **Step 2: Add auth status styles to popup.css**

Open `extension/popup/popup.css`. Append at the end:

```css
#scdb-auth {
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.5;
}

.auth-email {
  font-weight: 600;
  word-break: break-all;
  margin-bottom: 10px;
}

.auth-muted {
  color: var(--muted, #94a3b8);
  margin-bottom: 10px;
}

.auth-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.auth-btn {
  display: block;
  width: 100%;
  padding: 7px 12px;
  border: none;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  text-align: center;
  text-decoration: none;
}

.auth-btn-primary {
  background: #3b82f6;
  color: #fff;
}

.auth-btn-secondary {
  background: #1e293b;
  color: #94a3b8;
  border: 1px solid #334155;
}
```

- [ ] **Step 3: Add Digivault domain detection to popup.js**

Open `extension/popup/popup.js`. Replace the entire file with the following (it extends the existing logic by adding a domain check before rendering):

```javascript
document.getElementById("open-options")?.addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

// Resolve the configured server hostname (mirrors content.js logic).
async function getScdbHost() {
  const { serverUrl } = await new Promise((resolve) =>
    chrome.storage.sync.get("serverUrl", resolve)
  );
  return new URL(
    (serverUrl || "https://digivault.digilatics.co").replace(/\/$/, "")
  ).hostname;
}

async function maybeShowAuthStatus(tabHostname) {
  const scdbHost = await getScdbHost();
  if (tabHostname !== scdbHost) return false;

  // On the Digivault domain: show extension auth state.
  document.getElementById("root").style.display = "none";
  const panel = document.getElementById("scdb-auth");
  panel.style.display = "block";

  const { access, email } = await new Promise((resolve) =>
    chrome.storage.local.get(["access", "email"], resolve)
  );

  if (access && email) {
    panel.innerHTML = `
      <p class="auth-email">${escapeHtml(email)}</p>
      <div class="auth-actions">
        <a class="auth-btn auth-btn-primary"
           href="https://${escapeHtml(scdbHost)}/dashboard"
           target="_blank" rel="noopener noreferrer">
          Open Dashboard →
        </a>
        <button class="auth-btn auth-btn-secondary" id="ext-logout">
          Sign out of extension
        </button>
      </div>
    `;
    document.getElementById("ext-logout").addEventListener("click", async () => {
      await chrome.storage.local.remove(["access", "refresh", "email"]);
      panel.innerHTML = `<p class="auth-muted">Signed out.</p>`;
    });
  } else {
    panel.innerHTML = `
      <p class="auth-muted">Sign in to the extension to enable autofill on this site.</p>
      <div class="auth-actions">
        <button class="auth-btn auth-btn-primary" id="open-settings">
          Open Settings
        </button>
      </div>
    `;
    document.getElementById("open-settings").addEventListener("click", () => {
      chrome.runtime.openOptionsPage();
    });
  }

  return true;
}

chrome.tabs.query({ active: true, currentWindow: true }, async ([tab]) => {
  let tabHostname = "";
  try { tabHostname = new URL(tab?.url ?? "").hostname; } catch { /* non-url tab */ }

  const handled = await maybeShowAuthStatus(tabHostname);
  if (handled) return;

  // Default: existing site-data flow.
  chrome.runtime.sendMessage({ type: "GET_DATA" }, (data) => {
    const root = document.getElementById("root");

    if (chrome.runtime.lastError || !data || !data.registered) {
      root.innerHTML = `
        <div class="not-registered">
          <p class="muted">This site is not registered</p>
          <p class="muted">with Digivault.</p>
        </div>
      `;
      return;
    }

    const unknownCount = data.scripts.filter(s => s.provider === "unknown").length;
    const unknownBadge = data.has_unknown
      ? `<span class="badge orange">${unknownCount} unknown</span>`
      : `<span class="badge green">all known</span>`;

    const scriptRows = data.scripts.map(s => {
      const isUnknown = s.provider === "unknown";
      return `
        <li class="script-row${isUnknown ? " unknown" : ""}">
          <span class="provider${isUnknown ? " unknown-provider" : ""}" title="${escapeHtml(s.provider)}">${escapeHtml(s.provider)}</span>
          <span class="category muted">${escapeHtml(s.category)}</span>
          <span class="domain muted" title="${escapeHtml(s.src_domain)}">${escapeHtml(s.src_domain)}</span>
        </li>
      `;
    }).join("");

    const moreCount = data.script_count - data.scripts.length;
    const moreRow = moreCount > 0
      ? `<li class="more-row">…and ${moreCount} more — see dashboard</li>`
      : "";

    root.innerHTML = `
      <div class="summary">
        <strong>${data.script_count}</strong>
        <span>scripts detected</span>
        ${unknownBadge}
      </div>
      <ul class="scripts">
        ${scriptRows}
        ${moreRow}
      </ul>
      <a class="link" href="https://digivault.digilatics.co/websites" target="_blank" rel="noopener noreferrer">Open dashboard →</a>
    `;
  });
});

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
```

- [ ] **Step 4: Commit**

```bash
git add extension/popup/popup.html extension/popup/popup.css extension/popup/popup.js
git commit -m "feat: show extension auth status in popup when on Digivault domain"
```

---

## Task 8: Smoke test end-to-end

- [ ] **Step 1: Run the full backend test suite**

```bash
pytest --tb=short -q
```

Expected: all tests pass, no regressions.

- [ ] **Step 2: Reload extension and test popup auth status**

1. Go to `chrome://extensions`, click Reload on Digivault.
2. Navigate to `https://digivault.digilatics.co` (or your local frontend).
3. Click the extension icon — should show "Sign in to the extension…" if not logged in, or email + "Open Dashboard" if logged in.

- [ ] **Step 3: Test auto-login flow**

1. Log in to the extension via the options page.
2. Visit `https://digivault.digilatics.co/login` (or `http://localhost:3000/login` in dev).
3. Expect: brief redirect through `/auth/extension?code=…` then land on `/dashboard`.

- [ ] **Step 4: Test expired code (replay protection)**

1. In DevTools (background worker), call:
   ```javascript
   handleWebHandoff().then(r => console.log(r))
   ```
2. Copy the returned code.
3. Visit `/auth/extension?code=<that-code>` — should land on `/dashboard`.
4. Visit the same URL again immediately — should redirect to `/login?error=session_expired`.

- [ ] **Step 5: Final commit if any fixups needed**

```bash
git add -p
git commit -m "fix: address smoke test findings"
```
