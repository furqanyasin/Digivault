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
      await clearSession();
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

// MV3 chrome.action.* return promises that reject (e.g. "No tab with id") when
// the tab was closed between the event and the call — swallow both the sync
// throw and the async rejection so they don't surface as uncaught errors.
function actionSafe(promise) {
  try {
    if (promise && typeof promise.catch === "function") promise.catch(() => {});
  } catch { /* ignore */ }
}

function setBadgeSafe(props) {
  try { actionSafe(chrome.action.setBadgeText(props)); } catch { /* tab closed */ }
}

// The team's site hosts, cached so the badge can decide locally whether a tab
// is one of ours. The lookup used to be called, unauthenticated, with the
// hostname of every page every user visited — browsing history streamed to the
// server for sites that had nothing to do with Digivault.
const DOMAINS_TTL_MS = 10 * 60 * 1000;

async function getTeamDomains() {
  const { dv_domains } = await chrome.storage.session.get("dv_domains");
  if (dv_domains && Date.now() - dv_domains.at < DOMAINS_TTL_MS) return dv_domains.list;
  const apiBase = await getApiBase();
  const result = await authedFetch(`${apiBase}/api/extension/domains/`);
  if (result.error) return null;
  const list = (result.data ?? result).domains ?? [];
  await chrome.storage.session.set({ dv_domains: { at: Date.now(), list } });
  return list;
}

function bareHost(hostname) {
  return (hostname || "").toLowerCase().replace(/^www\./, "");
}

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url?.startsWith("http")) return;

  const domain = bareHost(new URL(tab.url).hostname);
  const apiBase = await getApiBase();

  try {
    const domains = await getTeamDomains();
    if (!domains || !domains.includes(domain)) {
      setBadgeSafe({ text: "", tabId });
      await chrome.storage.session.remove(String(tabId));
      return;
    }

    const envelope = await authedFetch(
      `${apiBase}/api/extension/lookup/?domain=${encodeURIComponent(domain)}`
    );
    if (envelope.error) throw new Error(envelope.error);
    const data = envelope.data ?? envelope;

    await chrome.storage.session.set({ [String(tabId)]: data });

    if (!data.registered) {
      setBadgeSafe({ text: "", tabId });
      return;
    }

    const text = String(data.script_count);
    const color = data.has_unknown ? "#f97316" : "#22c55e";
    setBadgeSafe({ text, tabId });
    try { actionSafe(chrome.action.setBadgeBackgroundColor({ color, tabId })); } catch { /* tab closed */ }
    try { actionSafe(chrome.action.setBadgeTextColor({ color: "#ffffff", tabId })); } catch { /* tab closed */ }
  } catch {
    setBadgeSafe({ text: "", tabId });
    await chrome.storage.session.remove(String(tabId));
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove([
    String(tabId), `dv_pending_save:${tabId}`, `dv_multistep:${tabId}`, `dv_login_user:${tabId}`,
  ]);
});

const MULTISTEP_TTL_MS = 2 * 60 * 1000;
const LOGIN_USER_TTL_MS = 5 * 60 * 1000;

// The site a sign-in belongs to, loosely: the last two labels of the host
// (accounts.google.com -> google.com), so a step that hops subdomains still
// counts as the same sign-in. Deliberately coarse — it only ever continues a
// flow the user started by picking a login on the previous step.
function siteKey(hostname) {
  const parts = bareHost(hostname).split(".");
  // Two-part public suffixes (acme.co.uk, acme.com.au) keep three labels, or
  // every .co.uk site would count as one.
  const twoPartSuffix =
    parts.length >= 3 && parts[parts.length - 1].length === 2 && parts[parts.length - 2].length <= 3;
  return parts.slice(twoPartSuffix ? -3 : -2).join(".");
}

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

  // Two-step sign-in state, per tab and tied to the site it started on: the
  // credential picked on the username step, and the username typed there (for
  // the save prompt on the password step). Short-lived on purpose.
  if (msg.type === "SET_MULTISTEP" || msg.type === "SET_LOGIN_USERNAME") {
    const tabId = sender.tab?.id;
    if (tabId == null || !sender.url) return reply({ error: "no_tab" });
    const key = msg.type === "SET_MULTISTEP" ? `dv_multistep:${tabId}` : `dv_login_user:${tabId}`;
    const value = msg.type === "SET_MULTISTEP"
      ? { credentialId: msg.credentialId }
      : { username: String(msg.username || "").slice(0, 320) };
    chrome.storage.session
      .set({ [key]: { ...value, host: siteKey(new URL(sender.url).hostname), ts: Date.now() } })
      .then(() => reply({ ok: true }));
    return true;
  }

  if (msg.type === "GET_MULTISTEP" || msg.type === "GET_LOGIN_USERNAME") {
    const isStep = msg.type === "GET_MULTISTEP";
    const key = `${isStep ? "dv_multistep" : "dv_login_user"}:${sender.tab?.id}`;
    const ttl = isStep ? MULTISTEP_TTL_MS : LOGIN_USER_TTL_MS;
    chrome.storage.session.get(key).then((stored) => {
      const v = stored[key];
      let ok = false;
      try {
        ok = !!v && Date.now() - v.ts < ttl && v.host === siteKey(new URL(sender.url).hostname);
      } catch { ok = false; }
      if (!ok) return reply(null);
      return reply(isStep ? { credentialId: v.credentialId } : v.username);
    });
    return true;
  }

  if (msg.type === "CLEAR_MULTISTEP") {
    chrome.storage.session.remove(`dv_multistep:${sender.tab?.id}`).then(() => reply({ ok: true }));
    return true;
  }

  // Should the save bar appear at all? See handleCheckSave.
  if (msg.type === "CHECK_SAVE") {
    handleCheckSave(msg).then(reply);
    return true;
  }

  if (msg.type === "DISMISS_SAVE") {
    const key = `${bareHost(msg.domain)}|${msg.username || ""}`;
    chrome.storage.session.get("dv_save_dismissed").then(({ dv_save_dismissed }) => {
      const map = { ...(dv_save_dismissed || {}), [key]: Date.now() };
      return chrome.storage.session.set({ dv_save_dismissed: map });
    }).then(() => reply({ ok: true }));
    return true;
  }

  if (msg.type === "NEVER_SAVE") {
    const host = bareHost(msg.domain);
    chrome.storage.local.get("dv_never_save").then(({ dv_never_save }) => {
      const list = Array.from(new Set([...(dv_never_save || []), host]));
      return chrome.storage.local.set({ dv_never_save: list });
    }).then(() => reply({ ok: true }));
    return true;
  }

  if (msg.type === "REPORT_BROKEN") {
    handleReportBroken(msg.credentialId, msg.note).then(reply);
    return true;
  }

  if (msg.type === "GET_TOTP") {
    handleGetTotp(msg.credentialId).then(reply);
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

  // Session hand-over from the dashboard. Only ever honoured from the
  // dashboard's own top-level page: the content script runs on every site, and
  // it used to relay this from whichever page posted it — so any website could
  // sign the extension into an attacker's account (and collect every login the
  // user then "saved") or sign them out.
  if (msg.type === "WEB_AUTH_SYNC" || msg.type === "WEB_AUTH_LOGOUT") {
    isFromDashboard(sender).then((ok) => {
      if (!ok) return reply({ error: "forbidden" });
      if (msg.type === "WEB_AUTH_SYNC") return handleWebAuthSync(msg).then(reply);
      return clearSession().then(() => reply({ ok: true }));
    });
    return true;
  }

  // Save-prompt hand-off across a full-page navigation. Content scripts cannot
  // read chrome.storage.session (the old code tried, and the prompt after a
  // real page load never appeared), so it lives here, keyed to the tab that
  // submitted the login: no other tab's content script is handed the password.
  if (msg.type === "SET_PENDING_SAVE") {
    const tabId = sender.tab?.id;
    if (tabId == null) return reply({ error: "no_tab" });
    chrome.storage.session
      .set({ [`dv_pending_save:${tabId}`]: msg.pending })
      .then(() => reply({ ok: true }));
    return true;
  }

  if (msg.type === "GET_PENDING_SAVE") {
    const key = `dv_pending_save:${sender.tab?.id}`;
    chrome.storage.session.get(key).then((s) => reply(s[key] ?? null));
    return true;
  }

  if (msg.type === "CLEAR_PENDING_SAVE") {
    chrome.storage.session.remove(`dv_pending_save:${sender.tab?.id}`).then(() => reply({ ok: true }));
    return true;
  }

  // Content scripts can't read chrome.storage.session directly, so the popup
  // stashes the "open + autofill" hand-off here and the content script reads it
  // back through these two messages.
  if (msg.type === "GET_PENDING_AUTOFILL") {
    chrome.storage.session.get("dv_pending_autofill").then((s) =>
      reply(s.dv_pending_autofill ?? null)
    );
    return true;
  }

  if (msg.type === "CLEAR_PENDING_AUTOFILL") {
    chrome.storage.session.remove("dv_pending_autofill").then(() => reply({ ok: true }));
    return true;
  }
});

// ------------------------------------------------------------------
// Credential handlers
// ------------------------------------------------------------------

async function handleGetCredentials(domain) {
  const apiBase = await getApiBase();
  // An empty/absent domain asks for the full vault ("All items" tab); a domain
  // narrows to that site. The backend switches on the presence of the param.
  const url = domain
    ? `${apiBase}/api/extension/credentials/?domain=${encodeURIComponent(domain)}`
    : `${apiBase}/api/extension/credentials/`;
  const result = await authedFetch(url);
  if (result.error) return result;
  return { credentials: result.data ?? [] };
}

async function storeTokens(access, refresh, email) {
  await chrome.storage.local.set({ access, refresh, email: email || "" });
  // A new session may be a different team: drop the cached site list.
  await chrome.storage.session.remove("dv_domains");
}

async function clearSession() {
  await chrome.storage.local.remove(["access", "refresh", "email"]);
  await chrome.storage.session.remove("dv_domains");
}

function apiError(json, fallback) {
  return json?.errors?.[0]?.message ?? json?.errors?.[0]?.detail ?? json?.detail ?? fallback;
}

// Email + password, no authenticator code — the extension's own route. Most of
// the time this is never used: signing in to the dashboard hands its session
// to the extension (see the DIGIVAULT_EXTENSION_AUTH hand-over).
async function handleLogin(email, password) {
  const apiBase = await getApiBase();
  try {
    const res = await fetch(`${apiBase}/api/extension/token/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const json = await res.json();
    if (!res.ok) return { error: apiError(json, "Invalid email or password.") };
    const d = json.data ?? json;
    if (!d.access || !d.refresh) return { error: "Unexpected response from server." };
    await storeTokens(d.access, d.refresh, email);
    return { ok: true };
  } catch {
    return { error: "network" };
  }
}

async function isFromDashboard(sender) {
  if (sender.id !== chrome.runtime.id || !sender.tab || sender.frameId !== 0) return false;
  try {
    return new URL(sender.url).origin === new URL(await getApiBase()).origin;
  } catch {
    return false;
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

async function handleWebAuthSync({ access, refresh, email }) {
  if (!access || !refresh) return { error: "missing_tokens" };
  await storeTokens(access, refresh, email);
  return { ok: true };
}

// The current authenticator code for a credential — never its secret, which
// stays on the server. Every read is audited there.
async function handleGetTotp(credentialId) {
  if (!credentialId) return { error: "missing_id" };
  const apiBase = await getApiBase();
  const result = await authedFetch(
    `${apiBase}/api/extension/credentials/${credentialId}/totp/`,
    { method: "POST" }
  );
  if (result.error) return result;
  const d = result.data ?? result;
  return { code: d.code ?? "", expiresIn: d.expires_in ?? 0 };
}

// "Not now" quiets a login for this long (per browser session).
const SAVE_DISMISS_MS = 12 * 60 * 60 * 1000;

// Whether to offer saving this sign-in, and as a new login or an update.
// Quiet for sites marked "Never", for a login dismissed recently, and — asked
// of the vault, which compares server-side without revealing anything — for a
// login already saved with this exact password or one the user cannot change.
async function handleCheckSave({ domain, username, password }) {
  if (!domain || !username || !password) return { prompt: false };
  const host = bareHost(domain);
  const { dv_never_save } = await chrome.storage.local.get("dv_never_save");
  if ((dv_never_save || []).includes(host)) return { prompt: false };
  const { dv_save_dismissed } = await chrome.storage.session.get("dv_save_dismissed");
  const dismissedAt = (dv_save_dismissed || {})[`${host}|${username}`];
  if (dismissedAt && Date.now() - dismissedAt < SAVE_DISMISS_MS) return { prompt: false };

  const apiBase = await getApiBase();
  const result = await authedFetch(`${apiBase}/api/extension/credentials/check/`, {
    method: "POST",
    body: JSON.stringify({ domain, username, password }),
  });
  if (result.error) return { prompt: false };
  const status = (result.data ?? result).status;
  if (status === "new") return { prompt: true, mode: "save" };
  if (status === "changed") return { prompt: true, mode: "update" };
  return { prompt: false };
}

async function handleReportBroken(credentialId, note) {
  if (!credentialId) return { error: "missing_id" };
  const apiBase = await getApiBase();
  const result = await authedFetch(
    `${apiBase}/api/extension/credentials/${credentialId}/report-broken/`,
    { method: "POST", body: JSON.stringify({ note: note || "" }) }
  );
  if (result.error) return result;
  return { ok: true };
}

async function handleRevealCredential(credentialId) {
  if (!credentialId) return { error: "missing_id" };
  const apiBase = await getApiBase();
  // The autofill reveal. A share or grant with can_view_password=false still
  // needs the real password to fill the login form, so this route returns it
  // and logs the pull as AUTOFILL. The dashboard endpoint no longer honours a
  // for_autofill flag — anyone could append it and read a hidden password.
  const result = await authedFetch(
    `${apiBase}/api/extension/credentials/${credentialId}/reveal/`,
    { method: "POST" }
  );
  if (result.error) return result;
  const d = result.data ?? result;
  // `password_hidden` only ever comes back from the dashboard route, which
  // blanks the password when can_view_password is off. Reaching it here means
  // this build is talking to the wrong endpoint (an extension left on an old
  // version after the autofill route moved). Fail loudly: filling an empty
  // password looks like "autofill is broken" and hides the real cause.
  if (d.password_hidden) return { error: "wrong_reveal_route" };
  return { username: d.username ?? "", password: d.password ?? "" };
}
