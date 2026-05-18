document.getElementById("open-options")?.addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

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

  // Load script data and credentials in parallel
  const [scriptData, credData] = await Promise.all([
    new Promise((resolve) => chrome.runtime.sendMessage({ type: "GET_DATA" }, resolve)),
    new Promise((resolve) => chrome.runtime.sendMessage({ type: "GET_CREDENTIALS", domain: tabHostname }, resolve)),
  ]);

  const root = document.getElementById("root");
  const creds = (!credData || credData.error) ? [] : (credData.credentials ?? []);

  // ── Credentials section ────────────────────────────────────────────
  if (creds.length > 0) {
    const section = document.createElement("div");
    section.className = "creds-section";

    const header = document.createElement("div");
    header.className = "creds-header";
    header.textContent = `Passwords (${creds.length})`;
    section.appendChild(header);

    creds.forEach((cred) => {
      const item = document.createElement("div");
      item.className = "cred-item";
      item.innerHTML = `
        <div class="cred-info">
          <span class="cred-label">${escapeHtml(cred.label)}</span>
          <span class="cred-type">${escapeHtml(cred.credential_type)}</span>
        </div>
        <button class="cred-fill-btn" data-id="${escapeHtml(cred.id)}">Fill</button>
      `;
      section.appendChild(item);

      item.querySelector(".cred-fill-btn").addEventListener("click", function () {
        this.textContent = "…";
        this.disabled = true;
        const btn = this;

        chrome.runtime.sendMessage({ type: "REVEAL_CREDENTIAL", credentialId: cred.id }, (result) => {
          if (chrome.runtime.lastError || !result || result.error) {
            btn.textContent = "Error";
            return;
          }
          chrome.tabs.sendMessage(tab.id, { type: "AUTOFILL", username: result.username, password: result.password }, (r) => {
            if (chrome.runtime.lastError || !r?.ok) {
              btn.textContent = "No form";
              btn.disabled = false;
              return;
            }
            btn.textContent = "✓ Filled";
            setTimeout(() => window.close(), 700);
          });
        });
      });
    });

    root.appendChild(section);
  }

  // ── Script monitoring section ──────────────────────────────────────
  if (chrome.runtime.lastError || !scriptData || !scriptData.registered) {
    if (creds.length === 0) {
      root.innerHTML += `
        <div class="not-registered">
          <p class="muted">This site is not registered</p>
          <p class="muted">with Digivault.</p>
        </div>
      `;
    }
    return;
  }

  const unknownCount = scriptData.scripts.filter(s => s.provider === "unknown").length;
  const unknownBadge = scriptData.has_unknown
    ? `<span class="badge orange">${unknownCount} unknown</span>`
    : `<span class="badge green">all known</span>`;

  const scriptRows = scriptData.scripts.map(s => {
    const isUnknown = s.provider === "unknown";
    return `
      <li class="script-row${isUnknown ? " unknown" : ""}">
        <span class="provider${isUnknown ? " unknown-provider" : ""}" title="${escapeHtml(s.provider)}">${escapeHtml(s.provider)}</span>
        <span class="category muted">${escapeHtml(s.category)}</span>
        <span class="domain muted" title="${escapeHtml(s.src_domain)}">${escapeHtml(s.src_domain)}</span>
      </li>
    `;
  }).join("");

  const moreCount = scriptData.script_count - scriptData.scripts.length;
  const moreRow = moreCount > 0
    ? `<li class="more-row">…and ${moreCount} more — see dashboard</li>`
    : "";

  const scriptsDiv = document.createElement("div");
  scriptsDiv.innerHTML = `
    ${creds.length > 0 ? '<hr class="section-divider" />' : ""}
    <div class="summary">
      <strong>${scriptData.script_count}</strong>
      <span>scripts detected</span>
      ${unknownBadge}
    </div>
    <ul class="scripts">
      ${scriptRows}
      ${moreRow}
    </ul>
    <a class="link" href="https://digivault.digilatics.co/websites" target="_blank" rel="noopener noreferrer">Open dashboard →</a>
  `;
  root.appendChild(scriptsDiv);
});

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
