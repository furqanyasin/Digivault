(function () {
  var el = document.currentScript || (function () {
    var scripts = document.getElementsByTagName('script');
    return scripts[scripts.length - 1];
  })();
  var siteId = el && el.getAttribute('data-site');
  if (!siteId) return;

  var ingestUrl = (el.src || '').replace(/\/s\.js.*$/, '/ingest/');
  if (!ingestUrl || ingestUrl === '/ingest/') {
    ingestUrl = window.location.origin + '/api/ingest/';
  }

  // POST without credentials. navigator.sendBeacon always sends with
  // credentials mode "include", which browsers refuse for a cross-origin
  // response carrying `Access-Control-Allow-Origin: *` — the ingest endpoints
  // are unauthenticated and must never accept cookies, so every sendBeacon on
  // a client site died at the preflight with a CORS error and the site's
  // scripts, forms and errors never reached the backend. fetch() with
  // credentials omitted matches the server's `*` policy; keepalive keeps the
  // page-unload survival that was sendBeacon's reason for existing.
  function post(url, payload) {
    if (typeof fetch === 'function') {
      try {
        fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: payload,
          credentials: 'omit',
          keepalive: true
        });
        return;
      } catch (err) { /* fall through to XHR */ }
    }
    var xhr = new XMLHttpRequest();
    xhr.open('POST', url, true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.send(payload);
  }

  function isWpCore(src) {
    return src.indexOf('/wp-includes/') !== -1 || src.indexOf('/wp-admin/') !== -1;
  }

  // Everything this page load has shown us, keyed by src. Each post carries the
  // union rather than a fresh scan: we post at DOMContentLoaded, at 2.5s, and
  // after each DOM mutation burst, and the first of those fires before GTM has
  // injected GA4, Meta Pixel, Clarity and HubSpot. A per-post scan therefore
  // made the early posts look like a *smaller inventory of the page*, which the
  // backend could not tell apart from those tags having been uninstalled.
  var seenScripts = {};

  function collectScripts() {
    var tags = document.querySelectorAll('script');
    for (var i = 0; i < tags.length; i++) {
      var t = tags[i];
      var src = (t.src || '').trim();
      if (!src) continue;
      if (isWpCore(src)) continue;
      var loc = 'unknown';
      if (document.head && document.head.contains(t)) loc = 'head';
      else if (document.body && document.body.contains(t)) loc = 'body';
      // GTM, Meta Pixel, Hotjar, Clarity and HubSpot all detach their tag once
      // loaded, which reads as 'unknown'. Keep the real location we saw earlier
      // instead of overwriting it with the absence of one.
      if (loc === 'unknown' && seenScripts[src]) continue;
      seenScripts[src] = {
        src: src,
        location: loc,
        is_async: t.async || false,
        is_defer: t.defer || false,
        is_inline: false
      };
    }
    var scripts = [];
    for (var key in seenScripts) {
      if (Object.prototype.hasOwnProperty.call(seenScripts, key)) {
        scripts.push(seenScripts[key]);
      }
    }
    return scripts;
  }

  // Third-party form providers detected by iframe src. Fields inside a
  // cross-origin iframe cannot be read, so we record presence + provider only.
  var FORM_PROVIDERS = [
    { name: 'HubSpot', re: /(hsforms\.(net|com)|hubspot\.com\/forms)/i },
    { name: 'Typeform', re: /typeform\.com/i },
    { name: 'Jotform', re: /jotform\.(com|co)/i },
    { name: 'Mailchimp', re: /(list-manage\.com|mailchimp\.com)/i },
    { name: 'Google Forms', re: /docs\.google\.com\/forms/i },
    { name: 'Calendly', re: /calendly\.com/i },
    { name: 'Wufoo', re: /wufoo\.com/i },
    { name: 'Zoho Forms', re: /forms\.zoho\.(com|eu|in)/i }
  ];

  function describeField(inp) {
    var t = inp.type || 'text';
    var labelText = '';
    if (inp.id) {
      var lbl = document.querySelector('label[for="' + inp.id + '"]');
      if (lbl) labelText = (lbl.textContent || '').trim();
    }
    var tag = inp.tagName.toLowerCase();
    return {
      name: inp.name || '',
      type: tag === 'textarea' ? 'textarea' : tag === 'select' ? 'select' : t,
      label: labelText,
      required: inp.required || false
    };
  }

  function isFieldInput(inp) {
    var t = inp.type || 'text';
    return !(t === 'hidden' || t === 'submit' || t === 'button' || t === 'reset' || t === 'image');
  }

  // Walk up from an orphan input to a container that looks like a form: one
  // holding a submit-style control, or tagged via role/class/id. Falls back to
  // the input's parent so unrelated inputs aren't merged into one giant group.
  function formLikeContainer(inp) {
    var node = inp.parentElement;
    var depth = 0;
    while (node && depth < 8) {
      if (node.getAttribute && (node.getAttribute('role') === 'form')) return node;
      var idc = ((node.id || '') + ' ' + (node.className || '')).toLowerCase();
      if (typeof idc === 'string' && idc.indexOf('form') !== -1) return node;
      if (node.querySelector && node.querySelector(
        'button[type="submit"], input[type="submit"], button:not([type]), [role="button"]'
      )) return node;
      node = node.parentElement;
      depth++;
    }
    return inp.parentElement || inp;
  }

  // Descriptor + owning element for every form catalogued on this page load.
  // Submission counting looks the element up here and reports the SAME
  // descriptor that was ingested, so the server recomputes an identical
  // fingerprint. Rebuilding a descriptor at submit time cannot work: the
  // fingerprint covers detection_type, so a div-detected form described as
  // "native" hashes to something that was never stored.
  var trackedForms = [];

  function isEmailAddress(s) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s);
  }

  // Hidden input names that read as "where to send this" rather than a visitor
  // field. Bare "email"/"your-email" are deliberately excluded: on a real
  // form they are the visitor's address, not the destination, and multi-step
  // forms carry the visitor's email between steps in a hidden field.
  var RECIPIENT_NAME = /(_to|^to$|sendto|send_to|recipient|receiver|notify|mailto|mail_to|admin_email|notification|target_email|forward|destination|deliver|report)/i;

  var RECIPIENT_ATTRS = [
    'data-email', 'data-recipient', 'data-recipient-email', 'data-send-to',
    'data-mailto', 'data-email-to', 'data-notify-email', 'data-deliver-to'
  ];

  // Where a form's submissions are configured to go. Reads form *configuration*
  // only — the mailto: action, data-* attributes, and hidden input values
  // (which carry server-side config, never what a visitor types). A form whose
  // destination lives server-side (Contact Form 7, Formspree, Netlify) is
  // invisible here and returns "". Returns the first address found, preferring
  // the highest-confidence signal, else "".
  function detectRecipientEmail(formEl) {
    var action = formEl.getAttribute ? formEl.getAttribute('action') || '' : '';
    if (/^mailto:/i.test(action)) {
      var addr = action.replace(/^mailto:/i, '').split('?')[0].split(',')[0].trim();
      if (isEmailAddress(addr)) return addr.toLowerCase();
    }
    if (formEl.getAttribute) {
      for (var a = 0; a < RECIPIENT_ATTRS.length; a++) {
        var v = formEl.getAttribute(RECIPIENT_ATTRS[a]);
        if (v && isEmailAddress(v)) return v.toLowerCase();
      }
    }
    var hidden = formEl.querySelectorAll ? formEl.querySelectorAll('input[type="hidden"]') : [];
    var fallback = '';
    for (var h = 0; h < hidden.length; h++) {
      var val = (hidden[h].value || '').trim();
      if (!isEmailAddress(val)) continue;
      var name = (hidden[h].name || '').toLowerCase();
      if (RECIPIENT_NAME.test(name)) return val.toLowerCase();
      if (!fallback) fallback = val.toLowerCase();
    }
    return fallback;
  }

  function collectForms() {
    var result = [];
    trackedForms = [];

    // --- 1. Native <form> elements ---
    var forms = document.querySelectorAll('form');
    for (var i = 0; i < forms.length; i++) {
      var f = forms[i];
      var fieldList = [];
      var inputs = f.querySelectorAll('input, textarea, select');
      for (var j = 0; j < inputs.length; j++) {
        if (!isFieldInput(inputs[j])) continue;
        fieldList.push(describeField(inputs[j]));
      }
      var nativeDesc = {
        form_id: f.id || '',
        form_name: f.getAttribute('name') || '',
        form_action: f.action || '',
        form_method: (f.method || 'post').toLowerCase(),
        detection_type: 'native',
        provider: '',
        recipient_email: detectRecipientEmail(f),
        fields: fieldList
      };
      result.push(nativeDesc);
      trackedForms.push({ el: f, desc: nativeDesc });
    }

    // --- 2. Div-based forms: inputs not inside any <form> ---
    var allInputs = document.querySelectorAll('input, textarea, select');
    var groups = [];
    for (var k = 0; k < allInputs.length; k++) {
      var inp = allInputs[k];
      if (!isFieldInput(inp)) continue;
      if (inp.closest('form')) continue;
      var container = formLikeContainer(inp);
      var g = null;
      for (var gi = 0; gi < groups.length; gi++) {
        if (groups[gi].container === container) { g = groups[gi]; break; }
      }
      if (!g) { g = { container: container, fields: [] }; groups.push(g); }
      g.fields.push(describeField(inp));
    }
    for (var gj = 0; gj < groups.length; gj++) {
      var grp = groups[gj];
      var hasSubmit = grp.container.querySelector && grp.container.querySelector(
        'button[type="submit"], input[type="submit"], button:not([type]), [role="button"]'
      );
      // Noise filter: keep only groups with a submit control or 2+ fields.
      if (!hasSubmit && grp.fields.length < 2) continue;
      var domDesc = {
        form_id: grp.container.id || '',
        form_name: (grp.container.getAttribute && grp.container.getAttribute('name')) || '',
        form_action: '',
        form_method: 'post',
        detection_type: 'dom',
        provider: '',
        recipient_email: detectRecipientEmail(grp.container),
        fields: grp.fields
      };
      result.push(domDesc);
      trackedForms.push({ el: grp.container, desc: domDesc });
    }

    // --- 3. Embedded third-party forms (iframes) ---
    var iframes = document.querySelectorAll('iframe[src]');
    var seenSrc = {};
    for (var m = 0; m < iframes.length; m++) {
      var src = iframes[m].src || '';
      if (!src || seenSrc[src]) continue;
      for (var p = 0; p < FORM_PROVIDERS.length; p++) {
        if (FORM_PROVIDERS[p].re.test(src)) {
          seenSrc[src] = true;
          result.push({
            form_id: iframes[m].id || '',
            form_name: '',
            form_action: src,
            form_method: 'post',
            detection_type: 'embedded',
            provider: FORM_PROVIDERS[p].name,
            fields: []
          });
          break;
        }
      }
    }

    return result;
  }

  function send() {
    var scripts = collectScripts();
    var forms = collectForms();
    var payload = JSON.stringify({
      site_id: siteId,
      page_url: window.location.href,
      scripts: scripts,
      forms: forms,
      user_agent: navigator.userAgent,
      snippet_version: '1.11'
    });
    post(ingestUrl, payload);
  }

  var hasSent = false;
  function sendOnce() {
    hasSent = true;
    send();
  }

  // Initial send at page-ready
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(sendOnce, 0);
  } else {
    document.addEventListener('DOMContentLoaded', sendOnce);
  }

  // Delayed re-send: catches forms loaded by JS frameworks after DOMContentLoaded
  setTimeout(send, 2500);

  // Elementor popup: fires when any popup opens — re-send so popup forms are captured
  window.addEventListener('elementor/popup/show', function () {
    setTimeout(send, 300);
  });

  // Generic popup/modal open events (Bootstrap, jQuery UI, custom)
  document.addEventListener('shown.bs.modal', function () { setTimeout(send, 300); });
  document.addEventListener('dialogopen', function () { setTimeout(send, 300); });

  // MutationObserver: re-send whenever a new <script src> or <form> is added to the DOM.
  // Catches scripts/forms injected by inline loaders (GTM, Facebook Pixel, Hotjar, Elementor popups, etc.)
  if (typeof MutationObserver !== 'undefined') {
    var moTimer;
    var observer = new MutationObserver(function (mutations) {
      var shouldResend = false;
      for (var i = 0; i < mutations.length; i++) {
        var nodes = mutations[i].addedNodes;
        for (var j = 0; j < nodes.length; j++) {
          var node = nodes[j];
          if (node.nodeType !== 1) continue;
          // New <script src="..."> element (dynamically injected by inline loaders)
          if (node.tagName === 'SCRIPT' && node.src) {
            shouldResend = true;
            break;
          }
          // New <form> element (Elementor popups, etc.)
          if (node.tagName === 'FORM' || (node.querySelector && node.querySelector('form'))) {
            shouldResend = true;
            break;
          }
          // Subtree may contain script or form elements
          if (node.querySelector && (node.querySelector('script[src]') || node.querySelector('form'))) {
            shouldResend = true;
            break;
          }
        }
        if (shouldResend) break;
      }
      if (!shouldResend) return;
      clearTimeout(moTimer);
      moTimer = setTimeout(send, 400);
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
    // Stop observing after 30s to avoid overhead on long-lived pages
    setTimeout(function () { observer.disconnect(); }, 30000);
  }

  // ── Form submission error detection ─────────────────────────────────────
  // Watches for failure messages rendered by form plugins after a submit.
  // Never reads field values — only the plugin's own status text. The server
  // filters again (only mail/SMTP/5xx-style failures are stored) and redacts
  // any PII that leaks into status text.
  var formErrorsUrl = ingestUrl.replace(/\/ingest\/?$/, '/ingest/form-errors/');
  var jsErrorsUrl = ingestUrl.replace(/\/ingest\/?$/, '/ingest/js-errors/');
  var formSubmitUrl = ingestUrl.replace(/\/ingest\/?$/, '/ingest/form-submission/');
  var reportedErrors = {};

  // Count a native <form> submission. Describes the form the same way
  // collectForms() does so the server can match it by fingerprint. Only native
  // forms are countable — embedded third-party iframes never reach this event.
  // Descriptor of the tracked form containing `node`, or null. Walking the
  // catalogue rather than the DOM is what keeps the reported descriptor
  // byte-identical to the ingested one.
  function lookupTrackedForm(node) {
    for (var i = 0; i < trackedForms.length; i++) {
      var t = trackedForms[i];
      if (t.el && t.el.contains && t.el.contains(node)) return t.desc;
    }
    return null;
  }

  // Re-cataloguing walks the whole DOM, so throttle it: a submit-looking
  // control that belongs to no form at all must not rescan on every click.
  var lastRecatalogue = 0;
  var RECATALOGUE_MS = 1000;

  function trackedFormFor(node) {
    var desc = lookupTrackedForm(node);
    if (desc) return desc;
    // The form may not be in the catalogue at all: submitted before the first
    // collectForms(), or first rendered after the last one — an Elementor popup
    // opened past the 30s observer window is the common case. Checking only for
    // an *empty* catalogue missed that second case entirely, and every
    // submission on such a form was dropped. The server stores a form it first
    // sees on a submit report, so re-cataloguing here loses nothing.
    var now = new Date().getTime();
    if (now - lastRecatalogue < RECATALOGUE_MS) return null;
    lastRecatalogue = now;
    try { collectForms(); } catch (err) { return null; }
    return lookupTrackedForm(node);
  }

  // A submit event and a click on the submit button both fire for the same
  // send, and a multi-step form may re-click while the request is in flight.
  // Count one submission per form per window.
  var submitSeen = {};
  var SUBMIT_DEDUPE_MS = 3000;

  function sendFormSubmission(desc) {
    if (!desc) return;
    var names = [];
    for (var i = 0; i < desc.fields.length; i++) names.push(desc.fields[i].name);
    var key = desc.detection_type + '|' + desc.form_id + '|' + desc.form_action + '|' + names.join(',');
    var now = new Date().getTime();
    if (submitSeen[key] && now - submitSeen[key] < SUBMIT_DEDUPE_MS) return;
    submitSeen[key] = now;

    var payload = JSON.stringify({
      site_id: siteId,
      page_url: window.location.href,
      form: desc
    });
    post(formSubmitUrl, payload);
  }

  // Clicks on submit-style controls, for the forms a `submit` event never
  // covers: div-based forms with no <form> element at all, and multi-step or
  // AJAX forms whose final button is type="button" and posts via fetch.
  //
  // Note this measures submit *attempts*, which is what the native `submit`
  // event measured too: neither knows whether the server accepted it.
  var SUBMIT_CONTROL = 'button, input[type="submit"], input[type="image"], [role="button"]';

  // Step navigation, option pickers and utility buttons all sit inside the same
  // form as the real submit control, so counting every click inside a form made
  // one visitor walking a multi-step form look like several conversions — six
  // "Next" clicks reported three submissions on a live site. A click now counts
  // only when the control reads as a *final* submit.
  //
  // "continue" is treated as step navigation, which loses the occasional
  // "Continue to payment" submit — the deliberate trade, since it is far more
  // often a wizard's Next button.
  var NAV_TEXT = /\b(next|back|prev|previous|continue|skip|cancel|close|dismiss|reset|clear|search|filter|log\s?in|login|sign\s?in|forgot|show|hide|toggle|upload|browse|remove|delete|edit)\b/i;
  var SUBMIT_TEXT = /\b(submit|send|apply|subscribe|register|sign\s?up|get\s+(a\s+)?(quote|started|demo|estimate|audit|price)|request|book|reserve|schedule|confirm|finish|complete|pay|checkout|order|contact)\b/i;

  function controlLabel(control) {
    var text = (control.textContent || control.value || '').trim();
    if (!text) {
      text = control.getAttribute('aria-label') ||
        control.getAttribute('title') || control.name || '';
    }
    return String(text).slice(0, 120);
  }

  // True when clicking this control plausibly submits the form, rather than
  // moving between steps or picking an option.
  function isSubmitControl(control) {
    var type = (control.getAttribute('type') || '').toLowerCase();
    if (type === 'reset') return false;
    var label = controlLabel(control);
    // A step button is a step button even when it is a native submit — a
    // server-rendered wizard advances with type="submit".
    if (NAV_TEXT.test(label)) return false;
    if (type === 'submit' || type === 'image') return true;
    // A <button> with no type inside a real <form> submits by default.
    if (control.tagName === 'BUTTON' && !type && control.form) return true;
    // Otherwise only the label can identify the AJAX submit control.
    return SUBMIT_TEXT.test(label);
  }

  document.addEventListener('click', function (e) {
    try {
      var node = e.target;
      if (!node || !node.closest) return;
      var control = node.closest(SUBMIT_CONTROL);
      if (!control) return;
      if (!isSubmitControl(control)) return;
      var desc = trackedFormFor(control);
      if (desc) sendFormSubmission(desc);
    } catch (err) { /* never break the host page */ }
  }, true);


  function sendFormError(source, formId, message) {
    var key = (source + '|' + formId + '|' + message).slice(0, 200);
    if (reportedErrors[key]) return;
    reportedErrors[key] = true;
    var payload = JSON.stringify({
      site_id: siteId,
      page_url: window.location.href,
      source: source || '',
      form_id: formId || '',
      message: (message || '').slice(0, 500)
    });
    post(formErrorsUrl, payload);
  }

  function formSource(form) {
    var c = form && form.className ? String(form.className) : '';
    if (c.indexOf('wpcf7') !== -1) return 'Contact Form 7';
    if (c.indexOf('wpforms') !== -1) return 'WPForms';
    if (c.indexOf('elementor-form') !== -1) return 'Elementor Forms';
    if (c.indexOf('gform') !== -1) return 'Gravity Forms';
    if (c.indexOf('nf-form') !== -1 || c.indexOf('ninja') !== -1) return 'Ninja Forms';
    if (c.indexOf('forminator') !== -1) return 'Forminator';
    if (c.indexOf('hs-form') !== -1) return 'HubSpot';
    return 'unknown';
  }

  var FAILURE_RE = /(submission failed|failed to send|could not be sent|could not send|server error|internal error|error occurred|try again later|mail .{0,30}fail|smtp|\b50[0-4]\b)/i;

  // Contact Form 7 fires explicit DOM events — the highest-quality signal.
  document.addEventListener('wpcf7mailfailed', function (e) {
    var msg = (e.detail && e.detail.apiResponse && e.detail.apiResponse.message) || 'Mail send failed';
    var fid = e.detail && e.detail.contactFormId ? String(e.detail.contactFormId) : '';
    sendFormError('Contact Form 7', fid, msg);
  });

  // Generic path: after any submit, watch newly rendered text for ~20s.
  var watchForm = null;
  var watchUntil = 0;
  var errObserver = null;

  function checkErrorText(text) {
    if (!text || Date.now() > watchUntil) return;
    var t = String(text).trim();
    // Skip empty fragments and whole-page containers — status messages are short.
    if (t.length < 6 || t.length > 600) return;
    if (FAILURE_RE.test(t)) {
      var form = watchForm;
      var fid = form ? (form.id || form.getAttribute('name') || '') : '';
      sendFormError(formSource(form), fid, t.slice(0, 500));
    }
  }

  function scanNode(node) {
    if (node.nodeType === 3) { checkErrorText(node.nodeValue); return; }
    if (node.nodeType === 1) checkErrorText(node.textContent);
  }

  document.addEventListener('submit', function (e) {
    watchForm = e.target && e.target.tagName === 'FORM' ? e.target : null;
    watchUntil = Date.now() + 20000;
    if (watchForm) sendFormSubmission(trackedFormFor(watchForm) || null);
    if (errObserver || typeof MutationObserver === 'undefined') return;
    errObserver = new MutationObserver(function (mutations) {
      if (Date.now() > watchUntil) return;
      for (var i = 0; i < mutations.length; i++) {
        var m = mutations[i];
        if (m.type === 'characterData') { checkErrorText(m.target.nodeValue); continue; }
        for (var j = 0; j < m.addedNodes.length; j++) scanNode(m.addedNodes[j]);
      }
    });
    errObserver.observe(document.documentElement, { childList: true, characterData: true, subtree: true });
  }, true);

  // ── Uncaught JavaScript errors ─────────────────────────────────────────────
  // Capped per page load and deduplicated client-side: a script erroring inside
  // a loop can fire thousands of times, and the point is to learn that it broke,
  // not to relay every occurrence. Everything here is wrapped so a failure in
  // the reporter can never break the host page.
  var jsErrorsSent = {};
  var jsErrorCount = 0;
  var JS_ERROR_LIMIT = 10;
  var NEWLINE = String.fromCharCode(10);

  function sendJsError(message, sourceUrl, lineNo, colNo, stack) {
    try {
      if (!message || jsErrorCount >= JS_ERROR_LIMIT) return;
      var key = (message + '|' + (sourceUrl || '') + '|' + (lineNo || '')).slice(0, 250);
      if (jsErrorsSent[key]) return;
      jsErrorsSent[key] = true;
      jsErrorCount++;

      var payload = JSON.stringify({
        site_id: siteId,
        page_url: window.location.href,
        message: String(message).slice(0, 2000),
        source_url: String(sourceUrl || '').slice(0, 2048),
        line_no: typeof lineNo === 'number' ? lineNo : null,
        col_no: typeof colNo === 'number' ? colNo : null,
        // First frames only — a full trace can be enormous and adds little.
        stack: String(stack || '').split(NEWLINE).slice(0, 5).join(NEWLINE).slice(0, 4000)
      });
      post(jsErrorsUrl, payload);
    } catch (e) { /* never let reporting break the page */ }
  }

  // addEventListener rather than window.onerror: assigning onerror would clobber
  // any handler the site already has.
  window.addEventListener('error', function (e) {
    try {
      // Resource load failures (img/script/link) surface here too, with no
      // message and the element as target — not a script exception.
      if (e && e.target && e.target !== window && e.target.tagName) return;
      var err = e && e.error;
      sendJsError(
        (e && e.message) || (err && err.message),
        e && e.filename,
        e && e.lineno,
        e && e.colno,
        err && err.stack
      );
    } catch (_) {}
  });

  window.addEventListener('unhandledrejection', function (e) {
    try {
      var r = e && e.reason;
      var msg = r && r.message ? r.message : String(r);
      sendJsError('Unhandled promise rejection: ' + msg, '', null, null, r && r.stack);
    } catch (_) {}
  });

})();
