# Digivault Browser Extension

## What it does

The extension lets any team member browse to a registered website and instantly see which third-party scripts are running on the current page — without waiting for the tracking snippet to accumulate data. It queries the Digivault API and overlays a badge/panel showing script count, provider names, categories, and whether any unknowns were detected.

---

## Tech stack

- **Manifest V3** (Chrome + Edge; Firefox via MV3 compatibility)
- Vanilla JS — no build step required for the core; optional Vite/TypeScript for the popup UI
- No background script persistence — uses `service_worker` (MV3)

---

## File structure

```
extension/
├── manifest.json
├── background.js          # Service worker — badge updates, API calls
├── content.js             # Injected into pages — collects live scripts, posts to ingest
├── popup/
│   ├── popup.html
│   ├── popup.js           # Renders script list from background cache
│   └── popup.css
├── options/
│   ├── options.html       # API key + server URL config
│   └── options.js
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

---

## manifest.json

```json
{
  "manifest_version": 3,
  "name": "Digivault",
  "version": "1.0.0",
  "description": "Monitor third-party scripts on any registered website.",
  "permissions": ["activeTab", "storage", "scripting"],
  "host_permissions": ["<all_urls>"],
  "background": {
    "service_worker": "background.js"
  },
  "action": {
    "default_popup": "popup/popup.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    },
    "default_badge_text": ""
  },
  "options_ui": {
    "page": "options/options.html",
    "open_in_tab": false
  },
  "content_scripts": [
    {
      "matches": ["<all_urls>"],
      "js": ["content.js"],
      "run_at": "document_idle"
    }
  ]
}
```

---

## API

### Lookup (public, no auth)

```
GET https://digivault.digilatics.co/api/extension/lookup/?domain=<domain>
```

**Response:**
```json
{
  "data": {
    "registered": true,
    "domain": "example.com",
    "script_count": 12,
    "has_unknown": true,
    "scripts": [
      { "provider": "google-analytics", "category": "analytics", "src_domain": "www.google-analytics.com", "is_inline": false },
      { "provider": "unknown", "category": "unknown", "src_domain": "cdn.mystery.io", "is_inline": false }
    ]
  }
}
```

- Returns up to 10 scripts (total count always accurate)
- Rate limit: 300 requests/hour per IP
- No auth required

### Ingest (public, site_id auth)

```
POST https://digivault.digilatics.co/api/ingest/
Content-Type: application/json

{
  "site_id": "<site_id from data-site attribute>",
  "page_url": "https://example.com/page",
  "scripts": [
    {
      "src": "https://www.googletagmanager.com/gtm.js?id=GTM-XXXX",
      "location": "head",
      "is_async": true,
      "is_defer": false,
      "is_inline": false
    }
  ],
  "user_agent": "Mozilla/5.0...",
  "snippet_version": "1.1"
}
```

- Returns `202 Accepted` immediately
- Rate limit: 10,000 requests/day per IP

---

## background.js

Responsibilities:
1. Listen for tab `onUpdated` (status = "complete") events
2. Extract domain from the tab URL
3. Call `/api/extension/lookup/?domain=<domain>`
4. Cache result in `chrome.storage.session` keyed by `tabId`
5. Update the badge:
   - No data / not registered → clear badge
   - Registered, no unknowns → green badge with script count
   - Registered, has unknowns → orange badge with `?` + count
6. Expose cached data to popup via `chrome.runtime.onMessage`

```js
const API_BASE = "https://digivault.digilatics.co";

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url?.startsWith("http")) return;

  const domain = new URL(tab.url).hostname;
  try {
    const res = await fetch(`${API_BASE}/api/extension/lookup/?domain=${domain}`);
    const envelope = await res.json();
    const data = envelope.data ?? envelope;

    await chrome.storage.session.set({ [tabId]: data });

    if (!data.registered) {
      chrome.action.setBadgeText({ text: "", tabId });
      return;
    }

    const text = String(data.script_count);
    const color = data.has_unknown ? "#f97316" : "#22c55e";
    chrome.action.setBadgeText({ text, tabId });
    chrome.action.setBadgeBackgroundColor({ color, tabId });
  } catch {
    chrome.action.setBadgeText({ text: "", tabId });
  }
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "GET_DATA") {
    chrome.tabs.query({ active: true, currentWindow: true }, async ([tab]) => {
      const stored = await chrome.storage.session.get(String(tab?.id));
      reply(stored[String(tab?.id)] ?? null);
    });
    return true; // keep channel open for async reply
  }
});
```

---

## content.js

Responsibilities:
1. Find the Digivault snippet `<script data-site="...">` on the page (if present)
2. If found: collect all `<script>` tags and POST to `/api/ingest/`
3. This runs in addition to the embedded `s.js` — it gives the extension a chance to send data even if the user hasn't visited the page before

```js
(function () {
  const snippetEl = document.querySelector('script[data-site]');
  if (!snippetEl) return; // not a registered site — nothing to do

  const siteId = snippetEl.getAttribute('data-site');
  const scripts = Array.from(document.querySelectorAll('script[src]'))
    .map(t => ({
      src: t.src,
      location: document.head.contains(t) ? 'head' : 'body',
      is_async: t.async,
      is_defer: t.defer,
      is_inline: false
    }));

  if (!scripts.length) return;

  const API_BASE = snippetEl.src.replace(/\/s\.js.*$/, '') || 'https://digivault.digilatics.co';

  fetch(`${API_BASE}/api/ingest/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      site_id: siteId,
      page_url: location.href,
      scripts,
      user_agent: navigator.userAgent,
      snippet_version: 'extension-1.0'
    })
  }).catch(() => {});
})();
```

---

## popup/popup.html

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <link rel="stylesheet" href="popup.css" />
  <title>Digivault</title>
</head>
<body>
  <header>
    <img src="../icons/icon48.png" alt="" width="24" height="24" />
    <span>Digivault</span>
  </header>
  <main id="root">Loading…</main>
  <script src="popup.js"></script>
</body>
</html>
```

---

## popup/popup.js

```js
chrome.runtime.sendMessage({ type: "GET_DATA" }, (data) => {
  const root = document.getElementById("root");

  if (!data || !data.registered) {
    root.innerHTML = `<p class="muted">This site is not registered with Digivault.</p>`;
    return;
  }

  const unknownBadge = data.has_unknown
    ? `<span class="badge orange">${data.scripts.filter(s => s.provider === 'unknown').length} unknown</span>`
    : '';

  root.innerHTML = `
    <div class="summary">
      <strong>${data.script_count}</strong> scripts detected ${unknownBadge}
    </div>
    <ul class="scripts">
      ${data.scripts.map(s => `
        <li class="script-row">
          <span class="provider">${s.provider}</span>
          <span class="category muted">${s.category}</span>
          <span class="domain muted">${s.src_domain}</span>
        </li>
      `).join('')}
      ${data.script_count > data.scripts.length
        ? `<li class="muted">…and ${data.script_count - data.scripts.length} more in dashboard</li>`
        : ''}
    </ul>
    <a class="link" href="https://digivault.digilatics.co/websites" target="_blank">Open dashboard →</a>
  `;
});
```

---

## options/options.js

Stores a custom server URL (for self-hosted or staging instances):

```js
const form = document.getElementById("options-form");
const serverInput = document.getElementById("server-url");

chrome.storage.sync.get("serverUrl", ({ serverUrl }) => {
  serverInput.value = serverUrl || "https://digivault.digilatics.co";
});

form.addEventListener("submit", (e) => {
  e.preventDefault();
  chrome.storage.sync.set({ serverUrl: serverInput.value.trim() }, () => {
    document.getElementById("status").textContent = "Saved.";
    setTimeout(() => (document.getElementById("status").textContent = ""), 1500);
  });
});
```

---

## Badge behaviour

| State | Badge | Colour |
|---|---|---|
| Site not registered | _(hidden)_ | — |
| Registered, all known scripts | script count | Green `#22c55e` |
| Registered, ≥1 unknown script | script count | Orange `#f97316` |

---

## CORS

The `/api/extension/lookup/` and `/api/ingest/` endpoints already return `Access-Control-Allow-Origin: *` so the extension can call them from any origin without issues.

To verify:
```
curl -I "https://digivault.digilatics.co/api/extension/lookup/?domain=example.com"
# Access-Control-Allow-Origin: *  ← must be present
```

---

## Testing locally

1. Open `chrome://extensions` → Enable **Developer mode**
2. Click **Load unpacked** → select the `extension/` folder
3. Navigate to any website registered in your Digivault account
4. The badge shows the script count; click the icon to see the popup

---

## Packaging for the Chrome Web Store

```bash
cd extension
zip -r ../digivault-extension.zip . --exclude "*.DS_Store"
```

Upload `digivault-extension.zip` at [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole).
