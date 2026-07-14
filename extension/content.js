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

    // Style the shadow DOM with a constructed stylesheet (adoptedStyleSheets).
    // A <style> element would be blocked on sites with a strict `style-src`
    // CSP; constructed sheets are CSSOM and exempt. All UI CSS lives here so no
    // inline styles or <style> tags are ever injected into the page.
    applyShadowStyles(shadowRoot);
    return shadowRoot;
  }

  const SHADOW_CSS = `
    .ss-icon-btn {
      position: fixed; width: 24px; height: 24px; border: none;
      background: rgba(15,23,42,0.85); border-radius: 4px; cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      pointer-events: all; opacity: 0.75;
      transition: opacity 0.15s, background 0.15s; padding: 0;
    }
    .ss-icon-btn:hover { opacity: 1; background: rgba(59,130,246,0.9); }
    .ss-dropdown {
      position: fixed; background: #1e293b; border: 1px solid #334155;
      border-radius: 6px; padding: 4px 0; min-width: 230px; max-height: 200px;
      overflow-y: auto; pointer-events: all; box-shadow: 0 8px 24px rgba(0,0,0,0.5); z-index: 1;
    }
    .ss-cred-btn {
      display: flex; align-items: center; justify-content: space-between; gap: 8px;
      width: 100%; padding: 8px 12px; background: none; border: none; color: #f1f5f9;
      font-size: 13px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      cursor: pointer; text-align: left; pointer-events: all;
    }
    .ss-cred-btn:hover, .ss-cred-btn:focus { background: #293548; outline: none; }
    .ss-cred-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ss-type-chip {
      font-size: 11px; background: rgba(59,130,246,0.15); color: #93c5fd;
      padding: 1px 7px; border-radius: 999px; white-space: nowrap; flex-shrink: 0;
    }
    .ss-empty {
      padding: 10px 14px; color: #94a3b8; font-size: 12px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .dv-save-bar {
      position: fixed; top: 0; left: 0; right: 0; background: #0f172a;
      border-bottom: 2px solid #22c55e; padding: 10px 16px; display: flex;
      align-items: center; gap: 12px; pointer-events: all;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 13px; color: #f1f5f9; z-index: 2; box-shadow: 0 4px 16px rgba(0,0,0,0.4);
    }
    .dv-save-text { flex: 1; min-width: 0; }
    .dv-save-domain { color: #4ade80; font-weight: 600; }
    .dv-save-user { color: #94a3b8; font-size: 11px; margin-top: 2px;
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .dv-save-btn {
      padding: 5px 14px; border: none; border-radius: 5px; font-size: 12px;
      font-family: inherit; cursor: pointer; pointer-events: all; flex-shrink: 0; white-space: nowrap;
    }
    .dv-save-btn-primary { background: #22c55e; color: #fff; font-weight: 600; }
    .dv-save-btn-primary:hover { background: #16a34a; }
    .dv-save-btn-primary:disabled { opacity: 0.6; cursor: default; }
    .dv-save-btn-ghost { background: transparent; color: #94a3b8; }
    .dv-save-btn-ghost:hover { color: #f1f5f9; }
    /* helpers replacing former inline style attributes (CSP-safe) */
    .dv-icon-svg { flex-shrink: 0; }
    .dv-error { color: #f87171; }
  `;

  function applyShadowStyles(root) {
    try {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(SHADOW_CSS);
      root.adoptedStyleSheets = [...root.adoptedStyleSheets, sheet];
    } catch (_e) {
      // Legacy fallback (subject to page CSP, but better than nothing).
      const styleEl = document.createElement('style');
      styleEl.textContent = SHADOW_CSS;
      root.appendChild(styleEl);
    }
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
  let handoffAttempted = false;

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
          safeSendMessage(
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

    dd.addEventListener('keydown', (e) => {
      const btns = Array.from(dd.querySelectorAll('.ss-cred-btn'));
      const idx = btns.indexOf(e.target);
      if (e.key === 'ArrowDown') { e.preventDefault(); btns[Math.min(idx + 1, btns.length - 1)]?.focus(); }
      if (e.key === 'ArrowUp') { e.preventDefault(); btns[Math.max(idx - 1, 0)]?.focus(); }
      if (e.key === 'Escape') { dd.remove(); activeDropdown = null; }
    });

    const iconRect = iconBtn.getBoundingClientRect();
    Object.assign(dd.style, {
      top: `${iconRect.bottom + 4}px`,
      left: `${Math.max(4, iconRect.right - 230)}px`,
    });

    root.appendChild(dd);
    activeDropdown = dd;

    dd.querySelector('.ss-cred-btn')?.focus();

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

  function safeSendMessage(msg, callback) {
    try {
      chrome.runtime.sendMessage(msg, (response) => {
        if (chrome.runtime.lastError) return;
        callback(response);
      });
    } catch (e) {
      if (e.message?.includes('Extension context invalidated')) {
        observer.disconnect();
      }
    }
  }

  function run() {
    const pairs = findLoginPairs();
    if (pairs.length === 0) return;

    safeSendMessage(
      { type: 'GET_CREDENTIALS', domain: location.hostname },
      (response) => {
        if (!response || response.error || !response.credentials?.length) return;
        const creds = response.credentials;

        pairs.forEach((pair) => {
          injectIcon(pair, creds);

          // Single saved credential → auto-fill silently (like LastPass)
          if (creds.length === 1 && !pair.__dvAutofilled) {
            pair.__dvAutofilled = true;
            safeSendMessage({ type: 'REVEAL_CREDENTIAL', credentialId: creds[0].id }, (result) => {
              if (!result || result.error) return;
              // Small delay so the page's own JS finishes initialising the fields
              setTimeout(() => {
                fillField(pair.username, result.username);
                fillField(pair.password, result.password);
              }, 350);
            });
          }
        });
      }
    );
  }

  // ----------------------------------------------------------------
  // SPA support — re-run on significant DOM changes
  // ----------------------------------------------------------------

  let debounceTimer = null;
  const observer = new MutationObserver(() => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(run, 600);
  });

  observer.observe(document.body, { childList: true, subtree: true });

  run();

  // ----------------------------------------------------------------
  // Original ingest logic (preserved)
  // ----------------------------------------------------------------

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
      }).catch(() => { });
    }
  }
  // ----------------------------------------------------------------
  // Credential capture — save prompt (LastPass-style)
  // ----------------------------------------------------------------

  const PENDING_KEY = 'dv_pending_save';

  function escapeStr(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // Attach submit listeners to any form containing a login pair
  function attachSaveCapture() {
    const pairs = findLoginPairs();
    if (!pairs.length) return;

    pairs.forEach(({ username, password }) => {
      const form = username.closest('form') || password.closest('form');
      if (!form || form.__dvCapture) return;
      form.__dvCapture = true;

      form.addEventListener('submit', () => {
        const u = username.value.trim();
        const p = password.value;
        if (!u || !p) return;

        const pendingData = {
          domain: location.hostname,
          username: u,
          password: p,
          loginUrl: location.href,
          ts: Date.now(),
        };

        // Store for display on the next page (regular navigation)
        chrome.storage.session.set({ [PENDING_KEY]: pendingData });

        // SPA fix: poll until the password field leaves the DOM / becomes hidden.
        // When it does, the SPA completed login — show the bar immediately.
        let ticks = 0;
        const poll = setInterval(() => {
          ticks++;
          if (ticks > 12) { clearInterval(poll); return; } // give up after ~6 s
          if (!isVisible(password)) {
            clearInterval(poll);
            showSaveBar(pendingData);
          }
        }, 500);
      }, { once: true });
    });
  }

  // On every page load, check if a pending save came from a previous login submit
  function checkPendingSave() {
    chrome.storage.session.get(PENDING_KEY, (data) => {
      if (chrome.runtime.lastError) return;
      const pending = data[PENDING_KEY];
      if (!pending) return;

      // Expire after 90 seconds
      if (Date.now() - pending.ts > 90_000) {
        chrome.storage.session.remove(PENDING_KEY);
        return;
      }

      // If we're still on the same URL with a login form → login failed, skip
      if (location.href === pending.loginUrl && findLoginPairs().length > 0) return;

      // Don't show on another login page
      if (findLoginPairs().length > 0) return;

      showSaveBar(pending);
    });
  }

  function showSaveBar(pending) {
    const root = getOrCreateShadowRoot();
    if (root.querySelector('.dv-save-bar')) return;

    const bar = document.createElement('div');
    bar.className = 'dv-save-bar';
    bar.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" class="dv-icon-svg">
        <path d="M7 1L2 3v4c0 2.76 2.17 5.34 5 6 2.83-.66 5-3.24 5-6V3L7 1z" fill="#22c55e"/>
      </svg>
      <div class="dv-save-text">
        <div>Save login for <span class="dv-save-domain">${escapeStr(pending.domain)}</span> to Digivault?</div>
        <div class="dv-save-user">${escapeStr(pending.username)}</div>
      </div>
      <button class="dv-save-btn dv-save-btn-primary" id="dv-save-yes">Save</button>
      <button class="dv-save-btn dv-save-btn-ghost" id="dv-save-no">Not now</button>
    `;
    root.appendChild(bar);

    let autoTimer = setTimeout(dismiss, 20_000);

    function dismiss() {
      clearTimeout(autoTimer);
      bar.remove();
      chrome.storage.session.remove(PENDING_KEY);
    }

    bar.querySelector('#dv-save-no').addEventListener('click', dismiss);

    bar.querySelector('#dv-save-yes').addEventListener('click', () => {
      const saveBtn = bar.querySelector('#dv-save-yes');
      saveBtn.textContent = 'Saving…';
      saveBtn.disabled = true;
      clearTimeout(autoTimer);

      safeSendMessage({ type: 'SAVE_CREDENTIAL', ...pending }, (result) => {
        if (!result || result.error) {
          const msg = result?.detail || 'Could not save — is this domain registered in Digivault?';
          bar.querySelector('.dv-save-text').innerHTML =
            `<div class="dv-error">${escapeStr(msg)}</div>`;
          saveBtn.remove();
          bar.querySelector('#dv-save-no').textContent = 'Dismiss';
          chrome.storage.session.remove(PENDING_KEY);
          autoTimer = setTimeout(dismiss, 5_000);
          return;
        }

        const verb = result.action === 'updated' ? 'Updated' : 'Saved';
        bar.querySelector('.dv-save-text').innerHTML = `
          <div>✅ ${verb} to Digivault!</div>
          <div class="dv-save-user">${escapeStr(pending.username)} · ${escapeStr(pending.domain)}</div>
        `;
        saveBtn.remove();
        bar.querySelector('#dv-save-no').textContent = 'Dismiss';
        chrome.storage.session.remove(PENDING_KEY);
        autoTimer = setTimeout(dismiss, 3_000);
      });
    });
  }

  // ----------------------------------------------------------------
  // AUTOFILL message from popup — fill current page's login form
  // ----------------------------------------------------------------

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type !== 'AUTOFILL') return;
    const pairs = findLoginPairs();
    if (!pairs.length) { sendResponse({ error: 'no_form' }); return; }
    fillField(pairs[0].username, msg.username);
    fillField(pairs[0].password, msg.password);
    sendResponse({ ok: true });
  });

  // Re-attach capture on DOM changes (SPA login forms that appear dynamically)
  const captureObserver = new MutationObserver(() => attachSaveCapture());
  captureObserver.observe(document.body, { childList: true, subtree: true });

  attachSaveCapture();
  checkPendingSave();
  checkPendingAutofill();

  // ----------------------------------------------------------------
  // Pending autofill — when the user clicks "Open" in the popup, the
  // credential id is stashed in session storage and the site opened in a new
  // tab. On arrival we reveal that credential and fill the login form, retrying
  // briefly because the form may render after document_idle.
  // ----------------------------------------------------------------

  function checkPendingAutofill() {
    safeSendMessage({ type: 'GET_PENDING_AUTOFILL' }, (pending) => {
      if (!pending || !pending.credentialId) return;

      const wantHost = (pending.host || '').replace(/^www\./, '');
      const here = location.hostname.replace(/^www\./, '');
      // Only honor it on the intended host (guards against opening elsewhere).
      if (wantHost && here !== wantHost) return;

      let attempts = 0;
      const maxAttempts = 20; // ~10s at 500ms
      const timer = setInterval(() => {
        attempts += 1;
        const pairs = findLoginPairs();
        if (pairs.length) {
          clearInterval(timer);
          safeSendMessage(
            { type: 'REVEAL_CREDENTIAL', credentialId: pending.credentialId },
            (creds) => {
              if (creds && !creds.error) {
                fillField(pairs[0].username, creds.username);
                fillField(pairs[0].password, creds.password);
              }
            }
          );
          safeSendMessage({ type: 'CLEAR_PENDING_AUTOFILL' }, () => {});
        } else if (attempts >= maxAttempts) {
          clearInterval(timer);
          safeSendMessage({ type: 'CLEAR_PENDING_AUTOFILL' }, () => {});
        }
      }, 500);
    });
  }

  // ----------------------------------------------------------------
  // Web → Extension SSO: pick up tokens posted by the login page
  // ----------------------------------------------------------------

  window.addEventListener('message', (e) => {
    if (e.origin !== window.location.origin) return;
    if (e.data?.type === 'DIGIVAULT_EXTENSION_AUTH') {
      const { access, refresh, email } = e.data;
      if (!access || !refresh) return;
      safeSendMessage({ type: 'WEB_AUTH_SYNC', access, refresh, email: email || '' }, () => {});
    } else if (e.data?.type === 'DIGIVAULT_EXTENSION_LOGOUT') {
      // Portal signed out → clear the extension's stored session too.
      safeSendMessage({ type: 'WEB_AUTH_LOGOUT' }, () => {});
    }
  });

  // ----------------------------------------------------------------
  // Extension auto-login on the Digivault web app login page
  // ----------------------------------------------------------------

  (async function maybeHandoff() {
    if (handoffAttempted) return;

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
})();
