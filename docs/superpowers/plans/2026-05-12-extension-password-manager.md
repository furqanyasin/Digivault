# Extension Password Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LastPass-style autofill to the Digivault Chrome extension — detect login forms on visited pages, look up matching credentials from the dashboard, and fill them on demand.

**Architecture:** A new authenticated backend endpoint returns credential metadata by domain. The extension's background service worker fetches credentials using a stored JWT, and the content script injects a Shadow DOM icon into detected username fields. Clicking the icon reveals and fills credentials via the existing `/reveal/` endpoint.

**Tech Stack:** Django REST Framework (backend), Vanilla JS + Chrome Extension APIs MV3 (extension), pytest-django (tests)

---

## File Map

**Create:**
- `apps/credentials/extension_urls.py` — single route for the new endpoint
- `tests/credentials/test_extension_credentials.py` — API tests for the new endpoint

**Modify:**
- `apps/credentials/views.py` — add `ExtensionCredentialLookupView`
- `config/urls.py` — mount `api/extension/` routes
- `extension/background.js` — add `GET_CREDENTIALS`, `REVEAL_CREDENTIAL` handlers + token refresh
- `extension/content.js` — replace with full form detection + Shadow DOM autofill UI
- `extension/options/options.html` — add login section above server URL
- `extension/options/options.js` — add login/logout logic

---

## Task 1: Backend — Extension Credentials Lookup Endpoint

**Files:**
- Create: `tests/credentials/test_extension_credentials.py`
- Modify: `apps/credentials/views.py`
- Create: `apps/credentials/extension_urls.py`
- Modify: `config/urls.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/credentials/test_extension_credentials.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.credentials.services import CredentialService
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="ec_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="EC Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="EC Site", domain="ecsite.io")


@pytest.fixture
def credential(website, owner):
    return CredentialService.create(
        website=website,
        label="WordPress Admin",
        credential_type="wordpress",
        login_url="https://ecsite.io/wp-admin",
        username="admin",
        password="secret",
        notes="",
        created_by=owner,
    )


def _auth_client(user):
    client = APIClient()
    resp = client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "Pass123!"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['data']['access']}")
    return client


@pytest.mark.django_db
class TestExtensionCredentialsLookup:
    def test_unauthenticated_returns_401(self):
        client = APIClient()
        resp = client.get("/api/extension/credentials/", {"domain": "ecsite.io"})
        assert resp.status_code == 401

    def test_missing_domain_returns_400(self, owner, team):
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/")
        assert resp.status_code == 400

    def test_returns_credentials_for_matching_domain(self, owner, team, website, credential):
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/", {"domain": "ecsite.io"})
        assert resp.status_code == 200
        data = resp.data["data"]
        assert len(data) == 1
        assert data[0]["label"] == "WordPress Admin"
        assert data[0]["credential_type"] == "wordpress"
        assert data[0]["login_url"] == "https://ecsite.io/wp-admin"

    def test_response_never_contains_password(self, owner, team, website, credential):
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/", {"domain": "ecsite.io"})
        item = resp.data["data"][0]
        assert "password" not in item
        assert "_password" not in item
        assert "username" not in item

    def test_unknown_domain_returns_empty_list(self, owner, team):
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/", {"domain": "unknown.xyz"})
        assert resp.status_code == 200
        assert resp.data["data"] == []

    def test_domain_match_is_case_insensitive(self, owner, team, website, credential):
        client = _auth_client(owner)
        resp = client.get("/api/extension/credentials/", {"domain": "ECSITE.IO"})
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1

    def test_credentials_from_other_team_not_returned(self, owner, team, website, credential):
        other_owner = User.objects.create_user(email="other@test.com", password="Pass123!")
        TeamService.create(name="Other Agency", owner=other_owner)
        client = _auth_client(other_owner)
        resp = client.get("/api/extension/credentials/", {"domain": "ecsite.io"})
        assert resp.status_code == 200
        assert resp.data["data"] == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/credentials/test_extension_credentials.py -v
```

Expected: `FAILED` — `404` or connection errors because the endpoint doesn't exist yet.

- [ ] **Step 3: Add `ExtensionCredentialLookupView` to `apps/credentials/views.py`**

Add this import at the top of the existing imports block:

```python
# (already present) from rest_framework import generics, permissions, status
# (already present) from rest_framework.response import Response
```

Add this class at the end of `apps/credentials/views.py`:

```python
class ExtensionCredentialLookupView(generics.ListAPIView):
    """GET /api/extension/credentials/?domain=<domain>

    Returns credential metadata for all credentials belonging to websites
    in the user's active team whose domain matches the query param.
    Never returns plaintext — callers must use the /reveal/ endpoint.
    """

    serializer_class = CredentialSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def list(self, request, *args, **kwargs):
        domain = request.query_params.get("domain", "").strip()
        if not domain:
            return Response(
                {"error": "domain parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return Credential.objects.none()
        domain = self.request.query_params.get("domain", "").strip().lower()
        return Credential.objects.filter(
            website__team=team,
            website__domain__iexact=domain,
        )
```

- [ ] **Step 4: Create `apps/credentials/extension_urls.py`**

```python
from django.urls import path

from apps.credentials.views import ExtensionCredentialLookupView

urlpatterns = [
    path("credentials/", ExtensionCredentialLookupView.as_view(), name="extension-credentials"),
]
```

- [ ] **Step 5: Mount the new routes in `config/urls.py`**

Add one line after the existing credentials mount:

```python
# Credentials vault
path("api/v1/", include("apps.credentials.urls")),
# Extension autofill lookup (authenticated, no plaintext)
path("api/extension/", include("apps.credentials.extension_urls")),
```

- [ ] **Step 6: Run tests to confirm they pass**

```
pytest tests/credentials/test_extension_credentials.py -v
```

Expected: all 7 tests `PASSED`.

- [ ] **Step 7: Run the full test suite to check for regressions**

```
pytest --tb=short -q
```

Expected: no new failures.

- [ ] **Step 8: Commit**

```bash
git add apps/credentials/views.py apps/credentials/extension_urls.py config/urls.py tests/credentials/test_extension_credentials.py
git commit -m "feat: add extension credential lookup endpoint"
```

---

## Task 2: background.js — Auth Token Handling + New Message Handlers

**Files:**
- Modify: `extension/background.js`

The existing handlers (`onUpdated`, `onRemoved`, `GET_DATA`) stay unchanged. We add a token refresh helper and two new message handlers.

- [ ] **Step 1: Replace `extension/background.js` with the full updated version**

```js
const DEFAULT_API_BASE = "https://digivault.digilatics.co";

async function getApiBase() {
  const { serverUrl } = await chrome.storage.sync.get("serverUrl");
  return (serverUrl || DEFAULT_API_BASE).replace(/\/$/, "");
}

// ------------------------------------------------------------------
// Token helpers
// ------------------------------------------------------------------

async function getToken() {
  const { access } = await chrome.storage.local.get("access");
  return access || null;
}

async function tryRefreshToken(apiBase) {
  const { refresh } = await chrome.storage.local.get("refresh");
  if (!refresh) return null;
  try {
    const res = await fetch(`${apiBase}/api/v1/auth/token/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    });
    if (!res.ok) {
      await chrome.storage.local.remove(["access", "refresh", "email"]);
      return null;
    }
    const json = await res.json();
    const newAccess = json.data?.access ?? json.access;
    if (newAccess) {
      await chrome.storage.local.set({ access: newAccess });
      return newAccess;
    }
    return null;
  } catch {
    return null;
  }
}

async function authedFetch(url, options = {}) {
  const apiBase = await getApiBase();
  let token = await getToken();
  if (!token) return { error: "not_authenticated" };

  const doFetch = (t) =>
    fetch(url, {
      ...options,
      headers: {
        ...(options.headers || {}),
        Authorization: `Bearer ${t}`,
        "Content-Type": "application/json",
      },
    });

  let res = await doFetch(token);
  if (res.status === 401) {
    const refreshed = await tryRefreshToken(apiBase);
    if (!refreshed) return { error: "session_expired" };
    res = await doFetch(refreshed);
  }
  if (!res.ok) return { error: `http_${res.status}` };
  return await res.json();
}

// ------------------------------------------------------------------
// Existing: badge update on tab load
// ------------------------------------------------------------------

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url?.startsWith("http")) return;

  const domain = new URL(tab.url).hostname;
  const apiBase = await getApiBase();

  try {
    const res = await fetch(
      `${apiBase}/api/extension/lookup/?domain=${encodeURIComponent(domain)}`
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const envelope = await res.json();
    const data = envelope.data ?? envelope;

    await chrome.storage.session.set({ [String(tabId)]: data });

    if (!data.registered) {
      chrome.action.setBadgeText({ text: "", tabId });
      return;
    }

    const text = String(data.script_count);
    const color = data.has_unknown ? "#f97316" : "#22c55e";
    chrome.action.setBadgeText({ text, tabId });
    chrome.action.setBadgeBackgroundColor({ color, tabId });
    chrome.action.setBadgeTextColor({ color: "#ffffff", tabId });
  } catch {
    chrome.action.setBadgeText({ text: "", tabId });
    await chrome.storage.session.remove(String(tabId));
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(String(tabId));
});

// ------------------------------------------------------------------
// Message router
// ------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "GET_DATA") {
    chrome.tabs.query({ active: true, currentWindow: true }, async ([tab]) => {
      const key = String(tab?.id);
      const stored = await chrome.storage.session.get(key);
      reply(stored[key] ?? null);
    });
    return true;
  }

  if (msg.type === "GET_CREDENTIALS") {
    handleGetCredentials(msg.domain).then(reply);
    return true;
  }

  if (msg.type === "REVEAL_CREDENTIAL") {
    handleRevealCredential(msg.credentialId).then(reply);
    return true;
  }
});

// ------------------------------------------------------------------
// Credential handlers
// ------------------------------------------------------------------

async function handleGetCredentials(domain) {
  if (!domain) return { error: "missing_domain" };
  const apiBase = await getApiBase();
  const result = await authedFetch(
    `${apiBase}/api/extension/credentials/?domain=${encodeURIComponent(domain)}`
  );
  if (result.error) return result;
  // result is the envelope: { data: [...], errors: [], meta: {} }
  return { credentials: result.data ?? [] };
}

async function handleRevealCredential(credentialId) {
  if (!credentialId) return { error: "missing_id" };
  const apiBase = await getApiBase();
  const result = await authedFetch(
    `${apiBase}/api/v1/credentials/${credentialId}/reveal/`,
    { method: "POST" }
  );
  if (result.error) return result;
  const d = result.data ?? result;
  return { username: d.username ?? "", password: d.password ?? "" };
}
```

- [ ] **Step 2: Manual test — reload the extension and verify existing badge behaviour still works**

1. Open `chrome://extensions` → click **Reload** on Digivault.
2. Navigate to any website registered in Digivault.
3. Confirm the badge still shows the script count with the correct colour.
4. Open DevTools → **Service Worker** console — confirm no errors on startup.

- [ ] **Step 3: Commit**

```bash
git add extension/background.js
git commit -m "feat: add GET_CREDENTIALS and REVEAL_CREDENTIAL message handlers to background"
```

---

## Task 3: Options Page — Login / Logout UI

**Files:**
- Modify: `extension/options/options.html`
- Modify: `extension/options/options.js`

- [ ] **Step 1: Replace `extension/options/options.html` with the version that includes a login section**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self';" />
  <title>Digivault — Settings</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg: #0f172a; --surface: #1e293b; --border: #334155;
      --text: #f1f5f9; --muted: #94a3b8; --accent: #3b82f6;
      --green: #22c55e; --red: #ef4444; --radius: 6px;
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    body {
      background: var(--bg); color: var(--text); font-family: var(--font);
      font-size: 14px; line-height: 1.6; min-height: 100vh;
      display: flex; justify-content: center; padding: 40px 20px;
    }

    .container { width: 100%; max-width: 480px; }

    h1 {
      font-size: 18px; font-weight: 700; margin-bottom: 4px;
      display: flex; align-items: center; gap: 8px;
    }

    .subtitle { color: var(--muted); font-size: 13px; margin-bottom: 28px; }

    hr { border: none; border-top: 1px solid var(--border); margin: 28px 0; }

    h2 { font-size: 15px; font-weight: 600; margin-bottom: 16px; }

    .field { margin-bottom: 20px; }

    label { display: block; font-weight: 500; font-size: 13px; margin-bottom: 6px; }

    .hint { font-size: 12px; color: var(--muted); margin-top: 4px; }

    input[type="url"],
    input[type="email"],
    input[type="password"] {
      width: 100%; padding: 8px 12px;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); color: var(--text); font-size: 13px;
      outline: none; transition: border-color 0.15s;
    }

    input[type="url"] { font-family: monospace; }

    input:focus { border-color: var(--accent); }

    .actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }

    .btn {
      padding: 8px 20px; border: none; border-radius: var(--radius);
      font-size: 13px; font-weight: 600; cursor: pointer; transition: opacity 0.15s;
    }

    .btn-primary { background: var(--accent); color: #fff; }
    .btn-primary:hover { opacity: 0.85; }

    .btn-danger { background: var(--red); color: #fff; }
    .btn-danger:hover { opacity: 0.85; }

    .status-msg {
      font-size: 13px; font-weight: 500; min-height: 1.4em;
    }

    .status-msg.ok { color: var(--green); }
    .status-msg.err { color: var(--red); }

    .logged-in-info {
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
      padding: 10px 14px; background: var(--surface);
      border: 1px solid var(--border); border-radius: var(--radius);
      font-size: 13px; margin-bottom: 16px;
    }

    .logged-in-info span { flex: 1; color: var(--muted); }
    .logged-in-info strong { color: var(--green); }
  </style>
</head>
<body>
  <div class="container">
    <h1>⚙ Digivault Settings</h1>
    <p class="subtitle">Configure your account and server connection.</p>

    <!-- Login section -->
    <h2>Account</h2>

    <div id="logged-in-section" style="display:none">
      <div class="logged-in-info">
        <span>Logged in as <strong id="logged-in-email"></strong></span>
        <button class="btn btn-danger" id="logout-btn" type="button">Log out</button>
      </div>
    </div>

    <div id="login-section">
      <form id="login-form" novalidate>
        <div class="field">
          <label for="login-email">Email</label>
          <input type="email" id="login-email" autocomplete="email" required />
        </div>
        <div class="field">
          <label for="login-password">Password</label>
          <input type="password" id="login-password" autocomplete="current-password" required />
        </div>
        <div class="actions">
          <button class="btn btn-primary" type="submit">Log in</button>
          <span id="login-status" class="status-msg" role="status" aria-live="polite"></span>
        </div>
      </form>
    </div>

    <hr />

    <!-- Server URL section -->
    <h2>Server</h2>
    <form id="options-form" novalidate>
      <div class="field">
        <label for="server-url">API Server URL</label>
        <input
          type="url" id="server-url" name="server-url"
          placeholder="https://digivault.digilatics.co"
          required autocomplete="off" spellcheck="false"
        />
        <p class="hint">Leave as default unless using a self-hosted or staging server.</p>
      </div>
      <div class="actions">
        <button class="btn btn-primary" type="submit">Save</button>
        <span id="server-status" class="status-msg ok" role="status" aria-live="polite"></span>
      </div>
    </form>
  </div>

  <script src="options.js"></script>
</body>
</html>
```

- [ ] **Step 2: Replace `extension/options/options.js` with the full version including login/logout**

```js
const DEFAULT_URL = "https://digivault.digilatics.co";

// ------------------------------------------------------------------
// Server URL form (unchanged behaviour)
// ------------------------------------------------------------------

const optionsForm = document.getElementById("options-form");
const serverInput = document.getElementById("server-url");
const serverStatus = document.getElementById("server-status");

chrome.storage.sync.get("serverUrl", ({ serverUrl }) => {
  serverInput.value = serverUrl || DEFAULT_URL;
});

optionsForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const value = serverInput.value.trim() || DEFAULT_URL;
  chrome.storage.sync.set({ serverUrl: value }, () => {
    serverStatus.textContent = "Saved.";
    setTimeout(() => { serverStatus.textContent = ""; }, 1500);
  });
});

// ------------------------------------------------------------------
// Auth state display
// ------------------------------------------------------------------

function showAuthState() {
  chrome.storage.local.get(["access", "email"], ({ access, email }) => {
    const loggedIn = !!access;
    document.getElementById("logged-in-section").style.display = loggedIn ? "" : "none";
    document.getElementById("login-section").style.display = loggedIn ? "none" : "";
    if (loggedIn && email) {
      document.getElementById("logged-in-email").textContent = email;
    }
  });
}

showAuthState();

// ------------------------------------------------------------------
// Login form
// ------------------------------------------------------------------

const loginForm = document.getElementById("login-form");
const loginStatus = document.getElementById("login-status");

function setLoginStatus(msg, isError) {
  loginStatus.textContent = msg;
  loginStatus.className = `status-msg ${isError ? "err" : "ok"}`;
}

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  if (!email || !password) {
    setLoginStatus("Email and password are required.", true);
    return;
  }

  setLoginStatus("Logging in…", false);

  const { serverUrl } = await chrome.storage.sync.get("serverUrl");
  const base = (serverUrl || DEFAULT_URL).replace(/\/$/, "");

  try {
    const res = await fetch(`${base}/api/v1/auth/token/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const json = await res.json();

    if (!res.ok) {
      const msg = json.errors?.[0]?.detail ?? json.detail ?? "Invalid email or password.";
      setLoginStatus(msg, true);
      return;
    }

    const access = json.data?.access ?? json.access;
    const refresh = json.data?.refresh ?? json.refresh;

    await chrome.storage.local.set({ access, refresh, email });
    document.getElementById("login-password").value = "";
    setLoginStatus("", false);
    showAuthState();
  } catch {
    setLoginStatus("Could not reach server. Check the Server URL below.", true);
  }
});

// ------------------------------------------------------------------
// Logout
// ------------------------------------------------------------------

document.getElementById("logout-btn").addEventListener("click", async () => {
  await chrome.storage.local.remove(["access", "refresh", "email"]);
  showAuthState();
});
```

- [ ] **Step 3: Manual test — reload extension, open options page**

1. `chrome://extensions` → Reload Digivault.
2. Right-click the extension icon → **Options**.
3. Confirm the **Account** section shows the login form.
4. Enter valid Digivault credentials → click **Log in**.
5. Confirm the form is replaced by "Logged in as user@example.com" + Logout button.
6. Click **Log out** → confirm the login form reappears.
7. Try invalid credentials → confirm an error message appears.

- [ ] **Step 4: Commit**

```bash
git add extension/options/options.html extension/options/options.js
git commit -m "feat: add login/logout to extension options page"
```

---

## Task 4: content.js — Login Form Detection + Shadow DOM Autofill UI

**Files:**
- Modify: `extension/content.js`

- [ ] **Step 1: Replace `extension/content.js` with the full autofill implementation**

```js
(function () {
  'use strict';

  if (window.__ssAutofillInit) return;
  window.__ssAutofillInit = true;

  // ----------------------------------------------------------------
  // Shadow DOM host — one div in body, all UI lives inside its shadow
  // ----------------------------------------------------------------

  let shadowRoot = null;

  function getOrCreateShadowRoot() {
    if (shadowRoot) return shadowRoot;
    const host = document.createElement('div');
    host.setAttribute('data-digivault-ui', '');
    Object.assign(host.style, {
      all: 'initial',
      position: 'fixed',
      top: '0',
      left: '0',
      width: '0',
      height: '0',
      zIndex: '2147483647',
      pointerEvents: 'none',
    });
    document.body.appendChild(host);
    shadowRoot = host.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = `
      .ss-icon-btn {
        position: fixed;
        width: 24px;
        height: 24px;
        border: none;
        background: rgba(15,23,42,0.85);
        border-radius: 4px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        pointer-events: all;
        opacity: 0.75;
        transition: opacity 0.15s, background 0.15s;
        padding: 0;
      }
      .ss-icon-btn:hover { opacity: 1; background: rgba(59,130,246,0.9); }

      .ss-dropdown {
        position: fixed;
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 4px 0;
        min-width: 230px;
        max-height: 200px;
        overflow-y: auto;
        pointer-events: all;
        box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        z-index: 1;
      }

      .ss-cred-btn {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        width: 100%;
        padding: 8px 12px;
        background: none;
        border: none;
        color: #f1f5f9;
        font-size: 13px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        cursor: pointer;
        text-align: left;
        pointer-events: all;
      }
      .ss-cred-btn:hover, .ss-cred-btn:focus { background: #293548; outline: none; }

      .ss-cred-label {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .ss-type-chip {
        font-size: 11px;
        background: rgba(59,130,246,0.15);
        color: #93c5fd;
        padding: 1px 7px;
        border-radius: 999px;
        white-space: nowrap;
        flex-shrink: 0;
      }

      .ss-empty {
        padding: 10px 14px;
        color: #94a3b8;
        font-size: 12px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
    `;
    shadowRoot.appendChild(style);
    return shadowRoot;
  }

  // ----------------------------------------------------------------
  // Field detection helpers
  // ----------------------------------------------------------------

  function findLoginPairs() {
    const pairs = [];
    document.querySelectorAll('input[type="password"]').forEach((pwField) => {
      if (!isVisible(pwField)) return;
      const username = findUsernameField(pwField);
      if (username) pairs.push({ username, password: pwField });
    });
    return pairs;
  }

  function isVisible(el) {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function findUsernameField(pwField) {
    const all = Array.from(document.querySelectorAll(
      'input:not([type="hidden"]):not([type="submit"]):not([type="button"])' +
      ':not([type="checkbox"]):not([type="radio"]):not([type="password"])'
    ));
    const preceding = all.filter((inp) => {
      if (!isVisible(inp)) return false;
      return !!(pwField.compareDocumentPosition(inp) & Node.DOCUMENT_POSITION_PRECEDING);
    });
    const typed = preceding.filter((inp) => {
      const t = (inp.type || '').toLowerCase();
      return t === '' || t === 'text' || t === 'email';
    });
    return typed[typed.length - 1] || null;
  }

  // ----------------------------------------------------------------
  // Fill helper — dispatches events so frameworks (React, Vue) react
  // ----------------------------------------------------------------

  function fillField(field, value) {
    const nativeInputValue = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      'value'
    );
    nativeInputValue.set.call(field, value);
    field.dispatchEvent(new Event('input', { bubbles: true }));
    field.dispatchEvent(new Event('change', { bubbles: true }));
  }

  // ----------------------------------------------------------------
  // Icon + dropdown injection
  // ----------------------------------------------------------------

  const injected = new WeakSet();
  let activeDropdown = null;

  function injectIcon(pair, credentials) {
    if (injected.has(pair.username)) return;
    injected.add(pair.username);

    const root = getOrCreateShadowRoot();

    const iconBtn = document.createElement('button');
    iconBtn.className = 'ss-icon-btn';
    iconBtn.setAttribute('aria-label', 'Fill with Digivault');
    iconBtn.setAttribute('title', 'Fill with Digivault');
    iconBtn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M7 1L2 3v4c0 2.76 2.17 5.34 5 6 2.83-.66 5-3.24 5-6V3L7 1z" fill="#22c55e"/>
      </svg>
    `;

    positionIconBtn(iconBtn, pair.username);
    root.appendChild(iconBtn);

    // Re-position on scroll/resize
    const reposition = () => positionIconBtn(iconBtn, pair.username);
    window.addEventListener('scroll', reposition, { passive: true });
    window.addEventListener('resize', reposition, { passive: true });

    iconBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (activeDropdown) {
        activeDropdown.remove();
        activeDropdown = null;
        return;
      }
      openDropdown(pair, credentials, iconBtn, root);
    });
  }

  function positionIconBtn(btn, field) {
    const rect = field.getBoundingClientRect();
    Object.assign(btn.style, {
      top: `${rect.top + (rect.height - 24) / 2}px`,
      left: `${rect.right - 28}px`,
    });
  }

  function openDropdown(pair, credentials, iconBtn, root) {
    const dd = document.createElement('div');
    dd.className = 'ss-dropdown';

    if (credentials.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'ss-empty';
      empty.textContent = 'No credentials saved for this site.';
      dd.appendChild(empty);
    } else {
      credentials.forEach((cred) => {
        const btn = document.createElement('button');
        btn.className = 'ss-cred-btn';
        btn.setAttribute('tabindex', '0');

        const label = document.createElement('span');
        label.className = 'ss-cred-label';
        label.textContent = cred.label;

        const chip = document.createElement('span');
        chip.className = 'ss-type-chip';
        chip.textContent = cred.credential_type;

        btn.appendChild(label);
        btn.appendChild(chip);
        dd.appendChild(btn);

        btn.addEventListener('click', () => {
          dd.remove();
          activeDropdown = null;
          chrome.runtime.sendMessage(
            { type: 'REVEAL_CREDENTIAL', credentialId: cred.id },
            (result) => {
              if (!result || result.error) return;
              fillField(pair.username, result.username);
              fillField(pair.password, result.password);
              pair.username.focus();
            }
          );
        });
      });
    }

    // Keyboard navigation
    dd.addEventListener('keydown', (e) => {
      const btns = Array.from(dd.querySelectorAll('.ss-cred-btn'));
      const idx = btns.indexOf(e.target);
      if (e.key === 'ArrowDown') { e.preventDefault(); btns[Math.min(idx + 1, btns.length - 1)]?.focus(); }
      if (e.key === 'ArrowUp') { e.preventDefault(); btns[Math.max(idx - 1, 0)]?.focus(); }
      if (e.key === 'Escape') { dd.remove(); activeDropdown = null; }
    });

    // Position below the icon
    const iconRect = iconBtn.getBoundingClientRect();
    Object.assign(dd.style, {
      top: `${iconRect.bottom + 4}px`,
      left: `${Math.max(4, iconRect.right - 230)}px`,
    });

    root.appendChild(dd);
    activeDropdown = dd;

    // First button gets focus
    dd.querySelector('.ss-cred-btn')?.focus();

    // Close on outside click
    const closeOnOutside = (e) => {
      if (!root.contains(e.target) && !iconBtn.contains(e.target)) {
        dd.remove();
        activeDropdown = null;
        document.removeEventListener('click', closeOnOutside, true);
      }
    };
    setTimeout(() => document.addEventListener('click', closeOnOutside, true), 0);
  }

  // ----------------------------------------------------------------
  // Main detection run
  // ----------------------------------------------------------------

  function run() {
    const pairs = findLoginPairs();
    if (pairs.length === 0) return;

    chrome.runtime.sendMessage(
      { type: 'GET_CREDENTIALS', domain: location.hostname },
      (response) => {
        if (!response || response.error || !response.credentials?.length) return;
        pairs.forEach((pair) => injectIcon(pair, response.credentials));
      }
    );
  }

  // ----------------------------------------------------------------
  // SPA support — re-run when DOM changes significantly
  // ----------------------------------------------------------------

  let debounceTimer = null;
  const observer = new MutationObserver(() => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(run, 600);
  });

  observer.observe(document.body, { childList: true, subtree: true });

  // Initial run
  run();

  // Also run the original ingest logic if a snippet is present
  const snippetEl = document.querySelector('script[data-site]');
  if (snippetEl) {
    const siteId = snippetEl.getAttribute('data-site');
    const scripts = Array.from(document.querySelectorAll('script[src]')).map((t) => ({
      src: t.src,
      location: document.head.contains(t) ? 'head' : 'body',
      is_async: t.async,
      is_defer: t.defer,
      is_inline: false,
    }));

    if (scripts.length) {
      const apiBase =
        (snippetEl.src || '').replace(/\/s\.js.*$/, '') ||
        'https://digivault.digilatics.co';
      fetch(`${apiBase}/api/ingest/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          site_id: siteId,
          page_url: location.href,
          scripts,
          user_agent: navigator.userAgent,
          snippet_version: 'extension-1.0',
        }),
      }).catch(() => {});
    }
  }
})();
```

- [ ] **Step 2: Manual test — autofill on a site with saved credentials**

1. `chrome://extensions` → Reload Digivault.
2. Open the Options page and log in with your Digivault account.
3. Navigate to a site that has credentials saved in Digivault (e.g. the WordPress login at a registered domain).
4. Confirm a small green shield icon appears inside the username/email field on the right edge.
5. Click the icon — confirm a dropdown appears listing the saved credential(s) with label and type chip.
6. Click a credential — confirm both the username and password fields are filled.
7. Navigate to a site with no saved credentials — confirm no icon is injected.
8. Navigate to a page with no login form — confirm no icon is injected.

- [ ] **Step 3: Manual test — SPA navigation**

1. Open a site that uses client-side routing (e.g. a React app with a login route).
2. Navigate to a non-login page first, then click a link to the login page.
3. Confirm the icon appears without a page reload.

- [ ] **Step 4: Manual test — unauthenticated state**

1. Log out via Options.
2. Navigate to a site with a login form.
3. Confirm no icon is injected (background returns `{error: "not_authenticated"}`).

- [ ] **Step 5: Commit**

```bash
git add extension/content.js
git commit -m "feat: inject autofill icon into login forms via Shadow DOM"
```

---

## Task 5: Final Verification

- [ ] **Step 1: Run full backend test suite**

```
pytest --tb=short -q
```

Expected: all tests pass, no regressions.

- [ ] **Step 2: Reload extension and do end-to-end smoke test**

1. `chrome://extensions` → Reload.
2. Open Options → log in.
3. Navigate to a registered site with credentials → icon appears → fill works.
4. Navigate to an unregistered site → no icon, badge unchanged.
5. Log out → navigate to login-form page → no icon.

- [ ] **Step 3: Final commit if any loose files**

```bash
git status
# If anything unstaged:
git add -p
git commit -m "chore: extension password manager cleanup"
```
