// ─── Utilities ───────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function msg(type, payload) {
  return new Promise((resolve) =>
    chrome.runtime.sendMessage({ type, ...payload }, resolve)
  );
}

function storageGet(keys) {
  return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
}

function storageGetSync(keys) {
  return new Promise((resolve) => chrome.storage.sync.get(keys, resolve));
}

function storageRemove(keys) {
  return new Promise((resolve) => chrome.storage.local.remove(keys, resolve));
}

async function getServerHost() {
  const { serverUrl } = await storageGetSync("serverUrl");
  return new URL((serverUrl || "https://digivault.digilatics.co").replace(/\/$/, "")).origin;
}

// ─── State ────────────────────────────────────────────────────────────────────

let activeTab = "vault";
let currentTabHostname = "";
let cachedCreds = [];
let cachedScriptData = null;
let tipDismissed = false;

// ─── Screen helpers ───────────────────────────────────────────────────────────

function showScreen(name) {
  document.getElementById("screen-login").style.display = name === "login" ? "" : "none";
  document.getElementById("screen-main").style.display  = name === "main"  ? "" : "none";
}

function switchTab(name) {
  activeTab = name;
  document.querySelectorAll(".tab-pane").forEach((el) => { el.style.display = "none"; });
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === name);
  });
  const pane = document.getElementById("tab-" + name);
  if (pane) pane.style.display = "";

  if (name === "vault")     renderVault();
  if (name === "alerts")    renderAlerts();
  if (name === "generator") initGenerator();
  if (name === "account")   renderAccount();
}

// ─── LOGIN ────────────────────────────────────────────────────────────────────

const loginForm    = document.getElementById("login-form");
const loginEmail   = document.getElementById("login-email");
const loginPw      = document.getElementById("login-pw");
const loginError   = document.getElementById("login-error");
const loginSubmit  = document.getElementById("login-submit-btn");
const pwEyeBtn     = document.getElementById("pw-eye-btn");

pwEyeBtn.addEventListener("click", () => {
  const isText = loginPw.type === "text";
  loginPw.type = isText ? "password" : "text";
  pwEyeBtn.title = isText ? "Show password" : "Hide password";
});

document.getElementById("forgot-btn").addEventListener("click", async () => {
  const host = await getServerHost();
  chrome.tabs.create({ url: host + "/accounts/password/reset/" });
});

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const email    = loginEmail.value.trim();
  const password = loginPw.value;
  if (!email || !password) {
    loginError.textContent = "Please enter a password.";
    return;
  }
  loginError.textContent = "";
  loginSubmit.textContent = "Logging in…";
  loginSubmit.disabled = true;

  const result = await msg("LOGIN", { email, password });

  loginSubmit.textContent = "LOG IN";
  loginSubmit.disabled = false;

  if (chrome.runtime.lastError || !result) {
    loginError.textContent = "Could not reach the extension service. Try reloading.";
    return;
  }
  if (result.error) {
    loginError.textContent =
      result.error === "network"
        ? "Could not reach server. Check your connection."
        : result.error;
    return;
  }

  await initMain();
});

// ─── VAULT ────────────────────────────────────────────────────────────────────

document.querySelectorAll(".filter-tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    renderVault(btn.dataset.filter);
  });
});

document.getElementById("vault-search").addEventListener("input", (e) => {
  renderVault(null, e.target.value.trim().toLowerCase());
});

async function renderVault(filter, search) {
  if (filter === undefined || filter === null) {
    const activeFilter = document.querySelector(".filter-tab.active");
    filter = activeFilter ? activeFilter.dataset.filter : "site";
  }
  const body = document.getElementById("vault-body");

  let creds = cachedCreds;

  if (filter === "site") {
    creds = creds.filter((c) =>
      c.login_url
        ? new URL(c.login_url.startsWith("http") ? c.login_url : "https://" + c.login_url).hostname.replace(/^www\./, "") ===
          currentTabHostname.replace(/^www\./, "")
        : false
    );
  }

  if (search) {
    creds = creds.filter(
      (c) =>
        c.label.toLowerCase().includes(search) ||
        (c.credential_type ?? "").toLowerCase().includes(search)
    );
  }

  if (creds.length === 0) {
    body.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "empty-state";

    if (filter === "site" && !search) {
      if (!cachedScriptData || !cachedScriptData.registered) {
        empty.innerHTML = `
          <div class="empty-icon-wrap">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="1.5">
              <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>
            </svg>
          </div>
          <p class="empty-title">No saved passwords</p>
          <p class="empty-sub">Passwords saved for <strong>${escapeHtml(currentTabHostname || "this site")}</strong> will appear here.</p>
        `;
      } else {
        empty.innerHTML = `
          <div class="empty-icon-wrap">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#1a56db" stroke-width="1.5">
              <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
          </div>
          <p class="empty-title">No credentials saved</p>
          <p class="empty-sub">No logins stored for ${escapeHtml(currentTabHostname)}. Credentials saved from this site will appear here.</p>
        `;
      }
    } else {
      empty.innerHTML = `
        <div class="empty-icon-wrap">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="1.5">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
        </div>
        <p class="empty-title">No results</p>
        <p class="empty-sub">Nothing matches your search.</p>
      `;
    }

    body.appendChild(empty);
    return;
  }

  body.innerHTML = "";
  creds.forEach((cred) => {
    const card = document.createElement("div");
    card.className = "cred-card";
    const typeLabel = escapeHtml(
      { wordpress: "WordPress", cpanel: "cPanel", godaddy: "GoDaddy", cloudflare: "Cloudflare",
        ftp: "FTP/SFTP", shopify: "Shopify", namecheap: "Namecheap", hostinger: "Hostinger",
        wix: "Wix", webflow: "Webflow", custom: "Custom" }[cred.credential_type] ?? cred.credential_type
    );
    const domain = cred.login_url
      ? new URL(cred.login_url.startsWith("http") ? cred.login_url : "https://" + cred.login_url).hostname.replace(/^www\./, "")
      : "";

    card.innerHTML = `
      <div class="cred-icon">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
        </svg>
      </div>
      <div class="cred-info">
        <div class="cred-label">${escapeHtml(cred.label)}</div>
        <div class="cred-meta">${typeLabel}${domain ? " · " + escapeHtml(domain) : ""}</div>
      </div>
      <button class="cred-fill-btn" data-id="${escapeHtml(cred.id)}">Fill</button>
    `;

    card.querySelector(".cred-fill-btn").addEventListener("click", async function () {
      this.textContent = "…";
      this.disabled = true;
      const btn = this;

      const result = await msg("REVEAL_CREDENTIAL", { credentialId: cred.id });

      if (chrome.runtime.lastError || !result || result.error) {
        btn.textContent = "Error";
        btn.disabled = false;
        return;
      }

      chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
        chrome.tabs.sendMessage(
          tab.id,
          { type: "AUTOFILL", username: result.username, password: result.password },
          (r) => {
            if (chrome.runtime.lastError || !r?.ok) {
              btn.textContent = "No form";
              btn.disabled = false;
              return;
            }
            btn.textContent = "✓ Filled";
            btn.className = "cred-fill-btn filled";
            setTimeout(() => window.close(), 800);
          }
        );
      });
    });

    body.appendChild(card);
  });
}

// ─── GENERATOR ───────────────────────────────────────────────────────────────

function generatePassword(len, lower, upper, nums, syms) {
  const sets = [];
  if (lower) sets.push("abcdefghijklmnopqrstuvwxyz");
  if (upper) sets.push("ABCDEFGHIJKLMNOPQRSTUVWXYZ");
  if (nums)  sets.push("0123456789");
  if (syms)  sets.push("!@#$%^&*()_+-=[]{}|;:,.<>?");
  if (!sets.length) sets.push("abcdefghijklmnopqrstuvwxyz");

  const pool = sets.join("");
  let pw = "";
  // Guarantee at least one char from each set
  sets.forEach((s) => { pw += s[Math.floor(Math.random() * s.length)]; });
  for (let i = pw.length; i < len; i++) {
    pw += pool[Math.floor(Math.random() * pool.length)];
  }
  // Shuffle
  return pw.split("").sort(() => Math.random() - 0.5).join("");
}

function calcStrength(pw) {
  let score = 0;
  if (pw.length >= 8)  score++;
  if (pw.length >= 12) score++;
  if (pw.length >= 16) score++;
  if (/[a-z]/.test(pw)) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^a-zA-Z0-9]/.test(pw)) score++;
  if (score <= 2) return { label: "Weak",      pct: 20,  color: "#e02424" };
  if (score <= 4) return { label: "Fair",       pct: 45,  color: "#c27803" };
  if (score <= 5) return { label: "Good",       pct: 65,  color: "#2563eb" };
  if (score <= 6) return { label: "Strong",     pct: 82,  color: "#057a55" };
  return                  { label: "Very Strong", pct: 100, color: "#057a55" };
}

let genInitialized = false;

function initGenerator() {
  if (genInitialized) return;
  genInitialized = true;

  const pwEl       = document.getElementById("gen-password");
  const strengthEl = document.getElementById("gen-strength-text");
  const barEl      = document.getElementById("gen-strength-bar");
  const lenNum     = document.getElementById("gen-length-num");
  const slider     = document.getElementById("gen-slider");
  const lower      = document.getElementById("gen-lower");
  const upper      = document.getElementById("gen-upper");
  const numsChk    = document.getElementById("gen-nums");
  const symsChk    = document.getElementById("gen-syms");

  function refresh() {
    const len = parseInt(lenNum.value) || 16;
    const pw = generatePassword(len, lower.checked, upper.checked, numsChk.checked, symsChk.checked);
    pwEl.textContent = pw;
    const s = calcStrength(pw);
    strengthEl.textContent = s.label;
    strengthEl.style.color = s.color;
    barEl.style.width = s.pct + "%";
    barEl.style.background = s.color;
  }

  slider.addEventListener("input", () => {
    lenNum.value = slider.value;
    refresh();
  });

  lenNum.addEventListener("input", () => {
    const v = Math.min(64, Math.max(8, parseInt(lenNum.value) || 16));
    slider.value = v;
    refresh();
  });

  [lower, upper, numsChk, symsChk].forEach((c) => c.addEventListener("change", refresh));

  document.getElementById("gen-refresh-btn").addEventListener("click", refresh);

  document.getElementById("gen-copy-btn").addEventListener("click", () => {
    navigator.clipboard.writeText(pwEl.textContent).then(() => {
      const btn = document.getElementById("gen-copy-btn");
      btn.style.color = "#057a55";
      setTimeout(() => { btn.style.color = ""; }, 1200);
    });
  });

  document.getElementById("gen-dismiss-btn").addEventListener("click", () => {
    const banner = document.querySelector(".gen-tip-banner");
    if (banner) banner.style.display = "none";
  });

  document.getElementById("gen-history-btn").addEventListener("click", async () => {
    const host = await getServerHost();
    chrome.tabs.create({ url: host + "/credentials" });
  });

  refresh();
}

// ─── ALERTS ──────────────────────────────────────────────────────────────────

function renderAlerts() {
  const body = document.getElementById("alerts-body");
  body.innerHTML = "";

  if (!cachedScriptData || !cachedScriptData.registered) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = `
      <div class="empty-icon-wrap">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#1a56db" stroke-width="1.5">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
      </div>
      <p class="empty-title">Site not monitored</p>
      <p class="empty-sub">Add this site to Digivault to monitor third-party scripts and get security alerts.</p>
    `;
    body.appendChild(empty);
    return;
  }

  const scripts = cachedScriptData.scripts || [];
  const unknownCount = scripts.filter((s) => s.provider === "unknown").length;
  const hasUnknown = cachedScriptData.has_unknown || unknownCount > 0;

  // Update badge
  const badge = document.getElementById("nav-alerts-badge");
  if (unknownCount > 0) {
    badge.textContent = unknownCount;
    badge.style.display = "";
  }

  // Summary card
  const summary = document.createElement("div");
  summary.className = "alerts-summary-row";
  summary.innerHTML = `
    <span class="alerts-count">${cachedScriptData.script_count}</span>
    <span style="font-size:13px;color:#6b7280">scripts detected</span>
    ${hasUnknown
      ? `<span class="badge-pill badge-orange">${unknownCount} unknown</span>`
      : `<span class="badge-pill badge-green">all known</span>`
    }
  `;
  body.appendChild(summary);

  if (scripts.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = `
      <p class="empty-sub">No script details available yet.</p>
    `;
    body.appendChild(empty);
    return;
  }

  scripts.forEach((s) => {
    const card = document.createElement("div");
    const isUnknown = s.provider === "unknown";
    card.className = "alerts-script-card" + (isUnknown ? " unknown" : "");
    card.innerHTML = `
      <span class="script-provider${isUnknown ? " is-unknown" : ""}" title="${escapeHtml(s.provider)}">${escapeHtml(s.provider)}</span>
      <span class="script-cat">${escapeHtml(s.category)}</span>
      <span class="script-domain" title="${escapeHtml(s.src_domain)}">${escapeHtml(s.src_domain)}</span>
    `;
    body.appendChild(card);
  });

  const moreCount = cachedScriptData.script_count - scripts.length;
  if (moreCount > 0) {
    const more = document.createElement("p");
    more.style.cssText = "font-size:11px;color:#6b7280;text-align:center;padding:6px 0;";
    more.textContent = "…and " + moreCount + " more — see dashboard";
    body.appendChild(more);
  }
}

// ─── ACCOUNT ─────────────────────────────────────────────────────────────────

async function renderAccount() {
  const { email } = await storageGet("email");
  document.getElementById("account-email-txt").textContent = email || "Not signed in";

  const host = await getServerHost();
  document.getElementById("acc-dashboard-btn").href = host + "/dashboard";
  document.getElementById("acc-vault-btn").href     = host + "/credentials";
}

document.getElementById("acc-settings-btn").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

document.getElementById("acc-about-btn").addEventListener("click", async () => {
  const manifest = chrome.runtime.getManifest();
  alert("Digivault Extension v" + manifest.version + "\n\nMonitor third-party scripts and manage credentials for your websites.");
});

document.getElementById("acc-logout-btn").addEventListener("click", async () => {
  await storageRemove(["access", "refresh", "email"]);
  showScreen("login");
  loginEmail.value = "";
  loginPw.value = "";
  loginError.textContent = "";
});

// ─── BOTTOM NAV ──────────────────────────────────────────────────────────────

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

document.getElementById("vault-open-btn").addEventListener("click", async (e) => {
  e.preventDefault();
  const host = await getServerHost();
  chrome.tabs.create({ url: host + "/credentials" });
});

// ─── INIT ─────────────────────────────────────────────────────────────────────

async function initMain() {
  showScreen("main");

  // Load data in parallel
  const [scriptResult, credResult] = await Promise.all([
    msg("GET_DATA"),
    msg("GET_CREDENTIALS", { domain: currentTabHostname }),
  ]);

  cachedScriptData = scriptResult && !scriptResult.error ? scriptResult : null;
  cachedCreds = (!credResult || credResult.error) ? [] : (credResult.credentials ?? []);

  // Update alerts badge
  if (cachedScriptData && cachedScriptData.has_unknown) {
    const unknownCount = (cachedScriptData.scripts || []).filter((s) => s.provider === "unknown").length;
    if (unknownCount > 0) {
      const badge = document.getElementById("nav-alerts-badge");
      badge.textContent = unknownCount;
      badge.style.display = "";
    }
  }

  switchTab("vault");
}

async function init() {
  const [tab] = await new Promise((resolve) =>
    chrome.tabs.query({ active: true, currentWindow: true }, resolve)
  );

  try { currentTabHostname = new URL(tab?.url ?? "").hostname.replace(/^www\./, ""); } catch { /* non-url */ }

  const { access } = await storageGet("access");
  if (!access) {
    showScreen("login");
    return;
  }

  await initMain();
}

init();
