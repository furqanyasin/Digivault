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
    const res = await fetch(`${apiBase}/api/extension/token/refresh/`, {
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

function setBadgeSafe(props) {
  try { chrome.action.setBadgeText(props); } catch { /* tab closed */ }
}

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
      setBadgeSafe({ text: "", tabId });
      return;
    }

    const text = String(data.script_count);
    const color = data.has_unknown ? "#f97316" : "#22c55e";
    setBadgeSafe({ text, tabId });
    try { chrome.action.setBadgeBackgroundColor({ color, tabId }); } catch { /* tab closed */ }
    try { chrome.action.setBadgeTextColor({ color: "#ffffff", tabId }); } catch { /* tab closed */ }
  } catch {
    setBadgeSafe({ text: "", tabId });
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

  if (msg.type === "LOGIN") {
    handleLogin(msg.email, msg.password).then(reply);
    return true;
  }

  if (msg.type === "WEB_HANDOFF") {
    handleWebHandoff().then(reply);
    return true;
  }

  if (msg.type === "SAVE_CREDENTIAL") {
    handleSaveCredential(msg).then(reply);
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
  return { credentials: result.data ?? [] };
}

async function handleLogin(email, password) {
  const apiBase = await getApiBase();
  try {
    const res = await fetch(`${apiBase}/api/extension/token/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const json = await res.json();
    if (!res.ok) {
      const msg = json.errors?.[0]?.message ?? json.errors?.[0]?.detail ?? json.detail ?? "Invalid email or password.";
      return { error: msg };
    }
    const access = json.data?.access ?? json.access;
    const refresh = json.data?.refresh ?? json.refresh;
    await chrome.storage.local.set({ access, refresh, email });
    return { ok: true };
  } catch {
    return { error: "network" };
  }
}

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

async function handleSaveCredential({ domain, username, password, loginUrl }) {
  if (!domain || !username || !password) return { error: "missing_fields" };
  const apiBase = await getApiBase();
  const result = await authedFetch(`${apiBase}/api/extension/credentials/save/`, {
    method: "POST",
    body: JSON.stringify({ domain, username, password, login_url: loginUrl || "" }),
  });
  if (result.error) return result;
  return result.data ?? result;
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
