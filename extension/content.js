(function () {
  'use strict';

  if (window.__ssAutofillInit) return;
  window.__ssAutofillInit = true;

  // The script runs in every frame (manifest all_frames) so a login form inside
  // an iframe can be filled. Page-level work — the script ingest, the dashboard
  // hand-over, the save bar — happens in the top frame only.
  const IS_TOP = window.top === window;

  // ----------------------------------------------------------------
  // Shadow DOM host — one div in body, all UI lives inside its shadow
  // ----------------------------------------------------------------

  let shadowRoot = null;

  function getOrCreateShadowRoot() {
    if (shadowRoot) return shadowRoot;
    const host = document.createElement('div');
    host.setAttribute('data-stacksmonitor-ui', '');
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

  // Every visible password field, with the username field before it when the
  // page shows one. `username` is null on the second step of a username-first
  // sign-in (Google, Microsoft, many hosting panels), where the page asks for
  // the password alone.
  function findLoginPairs() {
    const pairs = [];
    document.querySelectorAll('input[type="password"]').forEach((pwField) => {
      if (!isVisible(pwField)) return;
      pairs.push({ username: findUsernameField(pwField), password: pwField });
    });
    return pairs;
  }

  const USERNAME_HINT = /(user|email|e-mail|login|account|identifier|signin)/i;

  // The first step of a username-first sign-in: a lone identifier field and no
  // password field yet. Recognised by what the field declares itself to be,
  // not by being the only input — a newsletter box is also a lone email field,
  // which is why an icon there only ever fills on a click.
  function findUsernameOnlyField() {
    if (document.querySelector('input[type="password"]') &&
        Array.from(document.querySelectorAll('input[type="password"]')).some(isVisible)) {
      return null;
    }
    const inputs = Array.from(document.querySelectorAll(
      'input[type="email"], input[type="text"], input:not([type])'
    )).filter(isVisible);
    return inputs.find((inp) => {
      const ac = (inp.getAttribute('autocomplete') || '').toLowerCase();
      if (ac.includes('username') || ac === 'email' || ac.includes('webauthn')) return true;
      const hint = [inp.name, inp.id, inp.getAttribute('aria-label'), inp.placeholder]
        .filter(Boolean).join(' ');
      return USERNAME_HINT.test(hint);
    }) || null;
  }

  // A field the user can actually see. Size alone is not enough: a page can
  // park an input at opacity 0, or 1x1 px, or behind visibility:hidden, and
  // collect whatever gets filled into it without the user ever seeing a form.
  function isVisible(el) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) return false;
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const cs = getComputedStyle(node);
      if (cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse') return false;
      if (parseFloat(cs.opacity) < 0.1) return false;
    }
    return true;
  }

  // Never fill over plain http: anything on the wire or a network attacker can
  // inject a form. localhost is exempt for development.
  function fillAllowedHere() {
    return location.protocol === 'https:' ||
      location.hostname === 'localhost' || location.hostname === '127.0.0.1';
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
    if (!fillAllowedHere() || !field.isConnected || !isVisible(field)) return;
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
  // anchor field -> { btn, reposition }. The button is position:fixed in our
  // own shadow root, so it outlives the field it points at: an SPA sign-in
  // (the dashboard's own among them) swaps the form out without a page load,
  // and the icon used to stay floating where the field had been.
  const icons = new Map();
  let activeDropdown = null;
  let handoffAttempted = false;

  function removeIcon(anchor) {
    const entry = icons.get(anchor);
    if (!entry) return;
    entry.btn.remove();
    window.removeEventListener('scroll', entry.reposition);
    window.removeEventListener('resize', entry.reposition);
    if (activeDropdown && entry.btn === activeDropdown.__dvIcon) {
      activeDropdown.remove();
      activeDropdown = null;
    }
    icons.delete(anchor);
    injected.delete(anchor);
  }

  // Drop icons whose field has left the page or been hidden; re-place the rest,
  // since a layout change moves a field without any scroll or resize.
  function pruneIcons() {
    icons.forEach((entry, anchor) => {
      if (!anchor.isConnected || !isVisible(anchor)) removeIcon(anchor);
      else entry.reposition();
    });
  }

  function injectIcon(pair, credentials) {
    const anchor = pair.username || pair.password;
    if (!anchor || injected.has(anchor)) return;
    // The credential lookup is async; the field may be gone by its answer.
    if (!anchor.isConnected || !isVisible(anchor)) return;
    injected.add(anchor);

    const root = getOrCreateShadowRoot();

    const iconBtn = document.createElement('button');
    iconBtn.className = 'ss-icon-btn';
    iconBtn.setAttribute('aria-label', 'Fill with Stacks Monitor');
    iconBtn.setAttribute('title', 'Fill with Stacks Monitor');
    iconBtn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M7 1L2 3v4c0 2.76 2.17 5.34 5 6 2.83-.66 5-3.24 5-6V3L7 1z" fill="#22c55e"/>
      </svg>
    `;

    positionIconBtn(iconBtn, anchor);
    root.appendChild(iconBtn);

    const reposition = () => positionIconBtn(iconBtn, anchor);
    window.addEventListener('scroll', reposition, { passive: true });
    window.addEventListener('resize', reposition, { passive: true });
    icons.set(anchor, { btn: iconBtn, reposition });

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
              if (pair.username) fillField(pair.username, result.username);
              if (pair.password) {
                fillField(pair.password, result.password);
              } else {
                // Username step of a two-step sign-in: remember the choice so
                // the password step (same site, within two minutes) fills
                // without a second pick. The user's click started this flow.
                safeSendMessage({ type: 'SET_MULTISTEP', credentialId: cred.id }, () => {});
              }
              (pair.username || pair.password).focus();
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
    dd.__dvIcon = iconBtn;
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
    pruneIcons();
    if (!fillAllowedHere()) return;
    let pairs = findLoginPairs();
    if (pairs.length === 0) {
      const userField = findUsernameOnlyField();
      if (!userField) return;
      pairs = [{ username: userField, password: null }];
    }

    // Second step of a sign-in the user started with a click on step one.
    const passwordSteps = pairs.filter((pr) => pr.password && !pr.password.value);
    if (passwordSteps.length) {
      safeSendMessage({ type: 'GET_MULTISTEP' }, (pending) => {
        if (!pending || !pending.credentialId) return;
        safeSendMessage({ type: 'CLEAR_MULTISTEP' }, () => {});
        safeSendMessage({ type: 'REVEAL_CREDENTIAL', credentialId: pending.credentialId }, (result) => {
          if (!result || result.error) return;
          const pr = passwordSteps[0];
          if (pr.username && !pr.username.value) fillField(pr.username, result.username);
          fillField(pr.password, result.password);
        });
      });
    }

    safeSendMessage(
      { type: 'GET_CREDENTIALS', domain: location.hostname },
      (response) => {
        if (!response || response.error || !response.credentials?.length) return;
        const creds = response.credentials;

        // Fill only on a click — the icon, the popup's Fill, or Open. A page
        // with one matching login used to be filled silently on load, which
        // hands the password to any script on that page (and to any form an
        // injected script draws) without the user doing anything.
        pairs.forEach((pair) => injectIcon(pair, creds));
      }
    );
  }

  // ----------------------------------------------------------------
  // SPA support — re-run on significant DOM changes
  // ----------------------------------------------------------------

  let debounceTimer = null;
  let pruneFrame = 0;
  const observer = new MutationObserver(() => {
    // Pruning is immediate (once per frame) so the icon goes with its field;
    // the full detection pass stays debounced.
    if (icons.size && !pruneFrame) {
      pruneFrame = requestAnimationFrame(() => { pruneFrame = 0; pruneIcons(); });
    }
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(run, 600);
  });


  // ----------------------------------------------------------------
  // Original ingest logic (preserved)
  // ----------------------------------------------------------------

  const snippetEl = IS_TOP ? document.querySelector('script[data-site]') : null;
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
        'https://stacksmonitor.com';
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

  function escapeStr(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // Save capture. A login is "submitted" by a form submit, an Enter in the
  // password field, or a click on a button while a password is typed — most
  // modern sign-ins (Google's among them) never fire a submit event at all.
  // Top frame only: a save bar drawn inside a small login iframe is unreadable.
  const armed = new WeakMap(); // password field -> value already captured

  function captureFrom(passwordField) {
    const p = passwordField.value;
    if (!p || armed.get(passwordField) === p) return;
    armed.set(passwordField, p);
    const userField = findUsernameField(passwordField);
    const typed = userField ? userField.value.trim() : '';

    const finish = (username) => {
      if (!username) return;
      // Only for a login that is new to the vault or whose password changed:
      // the prompt used to come back on every sign-in to a site already saved.
      safeSendMessage(
        { type: 'CHECK_SAVE', domain: location.hostname, username, password: p },
        (check) => { if (check && check.prompt) offer(username, check.mode); }
      );
    };

    const offer = (username, mode) => {
      const pendingData = {
        domain: location.hostname,
        username,
        password: p,
        loginUrl: location.href,
        ts: Date.now(),
        mode: mode === 'update' ? 'update' : 'save',
      };
      // Store for display on the next page (regular navigation). Through the
      // background: content scripts cannot reach chrome.storage.session.
      safeSendMessage({ type: 'SET_PENDING_SAVE', pending: pendingData }, () => {});

      // SPA: poll until the password field leaves the DOM / becomes hidden.
      // When it does, the SPA completed login — show the bar immediately.
      let ticks = 0;
      const poll = setInterval(() => {
        ticks++;
        if (ticks > 12) { clearInterval(poll); return; } // give up after ~6 s
        if (!passwordField.isConnected || !isVisible(passwordField)) {
          clearInterval(poll);
          showSaveBar(pendingData);
        }
      }, 500);
    };

    // A password-only step has no username on the page; use the one typed on
    // the previous step of this sign-in, if the background kept it.
    if (typed) finish(typed);
    else safeSendMessage({ type: 'GET_LOGIN_USERNAME' }, (u) => finish(u || ''));
  }

  function attachSaveCapture() {
    if (!IS_TOP) return;
    // Remember what was typed into a username-only first step.
    const userOnly = findUsernameOnlyField();
    if (userOnly && !userOnly.__dvRemember) {
      userOnly.__dvRemember = true;
      userOnly.addEventListener('change', () => {
        const u = userOnly.value.trim();
        if (u) safeSendMessage({ type: 'SET_LOGIN_USERNAME', username: u }, () => {});
      });
    }
    findLoginPairs().forEach(({ password }) => {
      if (password.__dvCapture) return;
      password.__dvCapture = true;
      const form = password.closest('form');
      if (form) form.addEventListener('submit', () => captureFrom(password));
      password.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') captureFrom(password);
      });
    });
  }

  // A click is a sign-in only when the button belongs to the password's own
  // form (or, for a form-less login, sits right beside it). Counting any click
  // on the page turned every button in an app that merely *shows* a password
  // field — Stacks Monitor's own edit dialog among them — into a save prompt.
  function sameLoginArea(button, passwordField) {
    const form = passwordField.closest('form');
    if (form) return form.contains(button) || button.form === form;
    let node = passwordField.parentElement;
    for (let i = 0; i < 6 && node; i++, node = node.parentElement) {
      if (node.contains(button)) return true;
    }
    return false;
  }

  function onPossibleSubmitClick(e) {
    const target = e.target instanceof Element ? e.target : null;
    const button = target && target.closest('button, [role="button"], input[type="submit"], input[type="button"]');
    if (!button) return;
    findLoginPairs().forEach(({ password }) => {
      if (password.value && sameLoginArea(button, password)) captureFrom(password);
    });
  }

  // On every page load, check if a pending save came from a previous login submit
  function clearPendingSave() {
    safeSendMessage({ type: 'CLEAR_PENDING_SAVE' }, () => {});
  }

  function checkPendingSave() {
    if (!IS_TOP) return;
    safeSendMessage({ type: 'GET_PENDING_SAVE' }, (pending) => {
      if (!pending) return;

      // Expire after 90 seconds
      if (Date.now() - pending.ts > 90_000) {
        clearPendingSave();
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
        <div>${pending.mode === 'update' ? 'Update the password for' : 'Save login for'} <span class="dv-save-domain">${escapeStr(pending.domain)}</span> ${pending.mode === 'update' ? 'in' : 'to'} Stacks Monitor?</div>
        <div class="dv-save-user">${escapeStr(pending.username)}</div>
      </div>
      <button class="dv-save-btn dv-save-btn-primary" id="dv-save-yes">${pending.mode === 'update' ? 'Update' : 'Save'}</button>
      <button class="dv-save-btn dv-save-btn-ghost" id="dv-save-no">Not now</button>
      <button class="dv-save-btn dv-save-btn-ghost" id="dv-save-never">Never for this site</button>
    `;
    root.appendChild(bar);

    let autoTimer = setTimeout(dismiss, 20_000);

    function dismiss() {
      clearTimeout(autoTimer);
      bar.remove();
      clearPendingSave();
    }

    // "Not now" quiets this login for a while; "Never" quiets the site for good.
    bar.querySelector('#dv-save-no').addEventListener('click', () => {
      safeSendMessage({ type: 'DISMISS_SAVE', domain: pending.domain, username: pending.username }, () => {});
      dismiss();
    });
    bar.querySelector('#dv-save-never').addEventListener('click', () => {
      safeSendMessage({ type: 'NEVER_SAVE', domain: pending.domain }, () => {});
      dismiss();
    });

    bar.querySelector('#dv-save-yes').addEventListener('click', () => {
      const saveBtn = bar.querySelector('#dv-save-yes');
      saveBtn.textContent = 'Saving…';
      saveBtn.disabled = true;
      clearTimeout(autoTimer);

      safeSendMessage({ type: 'SAVE_CREDENTIAL', ...pending }, (result) => {
        if (!result || result.error) {
          const msg = result?.detail || 'Could not save this login to Stacks Monitor.';
          bar.querySelector('.dv-save-text').innerHTML =
            `<div class="dv-error">${escapeStr(msg)}</div>`;
          saveBtn.remove();
          bar.querySelector('#dv-save-never')?.remove();
          bar.querySelector('#dv-save-no').textContent = 'Dismiss';
          clearPendingSave();
          autoTimer = setTimeout(dismiss, 5_000);
          return;
        }

        const verb = result.action === 'updated' ? 'Updated' : 'Saved';
        bar.querySelector('.dv-save-text').innerHTML = `
          <div>✅ ${verb} to Stacks Monitor!</div>
          <div class="dv-save-user">${escapeStr(pending.username)} · ${escapeStr(pending.domain)}</div>
        `;
        saveBtn.remove();
        bar.querySelector('#dv-save-never')?.remove();
        bar.querySelector('#dv-save-no').textContent = 'Dismiss';
        clearPendingSave();
        autoTimer = setTimeout(dismiss, 3_000);
      });
    });
  }

  // ----------------------------------------------------------------
  // AUTOFILL message from popup — fill current page's login form
  // ----------------------------------------------------------------

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type !== 'AUTOFILL') return;
    if (!fillAllowedHere()) { sendResponse({ error: 'insecure_page' }); return; }
    const pairs = findLoginPairs();
    if (!pairs.length) {
      // Username step of a two-step sign-in: fill what is there.
      const userOnly = findUsernameOnlyField();
      if (!userOnly) { sendResponse({ error: 'no_form' }); return; }
      fillField(userOnly, msg.username);
      sendResponse({ ok: true });
      return;
    }
    if (pairs[0].username) fillField(pairs[0].username, msg.username);
    fillField(pairs[0].password, msg.password);
    sendResponse({ ok: true });
  });

  // Re-attach capture on DOM changes (SPA login forms that appear dynamically)
  const captureObserver = new MutationObserver(() => attachSaveCapture());

  // Nothing — no fill icons, no save prompt — on Stacks Monitor itself. Its own
  // pages show password fields (the vault's edit dialog), and treating them as
  // a website login put a shield in the dialog's username box and offered to
  // "save" the credential being edited on every click.
  function startAutofill() {
    observer.observe(document.body, { childList: true, subtree: true });
    run();
    captureObserver.observe(document.body, { childList: true, subtree: true });
    if (IS_TOP) document.addEventListener('click', onPossibleSubmitClick, true);
    attachSaveCapture();
    checkPendingSave();
    checkPendingAutofill();
  }

  isOwnOrigin().then((onOwnOrigin) => { if (!onOwnOrigin) startAutofill(); });

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
                if (pairs[0].username) fillField(pairs[0].username, creds.username);
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

  // Listened for on the dashboard only. `e.origin === location.origin` is true
  // for every page's messages to itself, so the old check let any website post
  // its own tokens and sign the extension into an attacker's account. The
  // background re-checks the sender's URL as well.
  async function isOwnOrigin() {
    const { serverUrl } = await new Promise((resolve) =>
      chrome.storage.sync.get('serverUrl', resolve)
    );
    try {
      return location.origin === new URL((serverUrl || 'https://stacksmonitor.com').replace(/\/$/, '')).origin;
    } catch {
      return false;
    }
  }

  async function isDashboardPage() {
    const { serverUrl } = await new Promise((resolve) =>
      chrome.storage.sync.get('serverUrl', resolve)
    );
    try {
      const origin = new URL((serverUrl || 'https://stacksmonitor.com').replace(/\/$/, '')).origin;
      return window.top === window && location.origin === origin;
    } catch {
      return false;
    }
  }

  isDashboardPage().then((onDashboard) => {
    if (!onDashboard) return;
    window.addEventListener('message', onDashboardMessage);
    // The dashboard posts its session once on load, and that can land before
    // this listener exists (the origin check above is async). Saying we are
    // ready makes it post again, so signing in to the web app reliably signs
    // in the extension too.
    window.postMessage({ type: 'STACKSMONITOR_EXTENSION_READY' }, window.location.origin);
  });

  function onDashboardMessage(e) {
    if (e.source !== window || e.origin !== window.location.origin) return;
    if (e.data?.type === 'STACKSMONITOR_EXTENSION_AUTH') {
      const { access, refresh, email } = e.data;
      if (!access || !refresh) return;
      safeSendMessage({ type: 'WEB_AUTH_SYNC', access, refresh, email: email || '' }, () => {});
    } else if (e.data?.type === 'STACKSMONITOR_EXTENSION_LOGOUT') {
      // Portal signed out → clear the extension's stored session too.
      safeSendMessage({ type: 'WEB_AUTH_LOGOUT' }, () => {});
    }
  }

  // ----------------------------------------------------------------
  // Extension auto-login on the Stacks Monitor web app login page
  // ----------------------------------------------------------------

  (async function maybeHandoff() {
    if (handoffAttempted || !IS_TOP) return;

    const { serverUrl } = await new Promise((resolve) =>
      chrome.storage.sync.get("serverUrl", resolve)
    );
    const scdbHost = new URL(
      (serverUrl || "https://stacksmonitor.com").replace(/\/$/, "")
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
