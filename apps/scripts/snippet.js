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
  // `onStatus`, when given, is called with the HTTP status once the response
  // arrives. Only the heatmap uses it, and only to hear "stop": collection is
  // opt-in per site and the server is the only thing that knows, since this
  // file is one cached asset shared by every client site.
  function post(url, payload, onStatus) {
    if (typeof fetch === 'function') {
      try {
        var p = fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: payload,
          credentials: 'omit',
          keepalive: true
        });
        if (onStatus && p && typeof p.then === 'function') {
          p.then(function (res) {
            try { onStatus(res.status); } catch (err) { }
          }, function () { /* network error — say nothing, try again later */ });
        }
        return;
      } catch (err) { /* fall through to XHR */ }
    }
    var xhr = new XMLHttpRequest();
    xhr.open('POST', url, true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    if (onStatus) {
      xhr.onload = function () {
        try { onStatus(xhr.status); } catch (err) { }
      };
    }
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

  // Every URL the browser has fetched, from Resource Timing. A <script src> in
  // the DOM is not proof the script runs here: markup inserted through
  // innerHTML or DOMParser — a page that previews another site's HTML, a
  // "check your tags" tool, a CMS rendering stored markup — carries <script>
  // elements the browser never fetches or executes. Collected blindly, one such
  // page reported another company's whole stack as this site's, then reported
  // it removed when the preview changed, on repeat.
  //
  // `fetched` stays null (and every tag is trusted, the old behaviour) when the
  // API is missing, or when the timeline buffer was already full before this
  // snippet loaded, since entries dropped by a full buffer are unknowable.
  var fetched = null;
  try {
    if (typeof PerformanceObserver === 'function' && window.performance &&
        typeof performance.getEntriesByType === 'function') {
      var buffered = performance.getEntriesByType('resource');
      if (buffered.length < 250) {
        fetched = {};
        for (var r = 0; r < buffered.length; r++) fetched[stripHash(buffered[r].name)] = true;
        new PerformanceObserver(function (list) {
          var entries = list.getEntries();
          for (var e = 0; e < entries.length; e++) fetched[stripHash(entries[e].name)] = true;
        }).observe({ type: 'resource', buffered: true });
      }
    }
  } catch (err) { fetched = null; }

  function stripHash(url) {
    var h = (url || '').indexOf('#');
    return h === -1 ? url : url.slice(0, h);
  }

  // A consent manager parks a tag as <script type="text/plain" src=...> until
  // the visitor opts in. It is installed, just not running for this visitor, so
  // it is reported as present — the same answer the visitor who accepted gives.
  function isExecutableType(t) {
    var type = (t.getAttribute('type') || '').trim().toLowerCase();
    return !type || type === 'module' || type.indexOf('javascript') !== -1 ||
      type.indexOf('ecmascript') !== -1;
  }

  var awaitingFetch = false;

  function collectScripts() {
    awaitingFetch = false;
    var tags = document.querySelectorAll('script');
    for (var i = 0; i < tags.length; i++) {
      var t = tags[i];
      var src = (t.src || '').trim();
      if (!src) continue;
      if (isWpCore(src)) continue;
      // Not fetched (yet): either inert markup or still in flight. Skipped
      // rather than remembered, so a slow async tag is picked up by a later post.
      if (fetched && !seenScripts[src] && isExecutableType(t) &&
          !fetched[stripHash(src)]) {
        awaitingFetch = true;
        continue;
      }
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
  var CC_NAME = /(^cc$|_cc$|carbon)/i;
  var BCC_NAME = /(^bcc$|_bcc$|blind)/i;

  var RECIPIENT_ATTRS = [
    'data-email', 'data-recipient', 'data-recipient-email', 'data-send-to',
    'data-mailto', 'data-email-to', 'data-notify-email', 'data-deliver-to'
  ];

  // Where a form's submissions are configured to go, as {to, cc, bcc} of
  // comma-joined strings. Reads form *configuration* only — the mailto: action
  // (including its ?cc= and ?bcc= parameters), data-* attributes, and hidden
  // input values, which carry server-side config and never what a visitor
  // types. A form whose destination lives server-side (Contact Form 7,
  // Formspree, Netlify) is invisible here and yields empty strings.
  function detectRecipients(formEl) {
    var out = { to: '', cc: '', bcc: '' };
    var action = formEl.getAttribute ? formEl.getAttribute('action') || '' : '';

    if (/^mailto:/i.test(action)) {
      var body = action.replace(/^mailto:/i, '');
      var q = body.indexOf('?');
      out.to = q === -1 ? body : body.slice(0, q);
      if (q !== -1) {
        var pairs = body.slice(q + 1).split('&');
        for (var p = 0; p < pairs.length; p++) {
          var kv = pairs[p].split('=');
          var key = decodeURIComponent(kv[0] || '').toLowerCase();
          var val = decodeURIComponent((kv[1] || '').replace(/\+/g, ' '));
          if (key === 'cc') out.cc = out.cc ? out.cc + ',' + val : val;
          if (key === 'bcc') out.bcc = out.bcc ? out.bcc + ',' + val : val;
        }
      }
    }

    if (formEl.getAttribute) {
      for (var a = 0; a < RECIPIENT_ATTRS.length; a++) {
        var v = formEl.getAttribute(RECIPIENT_ATTRS[a]);
        if (v && isEmailAddress(v) && !out.to) out.to = v;
      }
    }

    var hidden = formEl.querySelectorAll ? formEl.querySelectorAll('input[type="hidden"]') : [];
    var fallback = '';
    for (var h = 0; h < hidden.length; h++) {
      var value = (hidden[h].value || '').trim();
      if (!isEmailAddress(value)) continue;
      var name = (hidden[h].name || '').toLowerCase();
      if (BCC_NAME.test(name)) { out.bcc = out.bcc ? out.bcc + ',' + value : value; continue; }
      if (CC_NAME.test(name)) { out.cc = out.cc ? out.cc + ',' + value : value; continue; }
      if (RECIPIENT_NAME.test(name)) { out.to = out.to ? out.to + ',' + value : value; continue; }
      if (!fallback) fallback = value;
    }
    if (!out.to && fallback) out.to = fallback;

    return out;
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
        recipients: detectRecipients(f),
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
        recipients: detectRecipients(grp.container),
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
      snippet_version: '1.14'
    });
    post(ingestUrl, payload);
    sentScriptCount = scripts.length;
    if (awaitingFetch) scheduleFetchRecheck();
  }

  // A tag GTM injects is posted 400ms after it appears, usually before its
  // download has finished, so collectScripts skips it as not-yet-fetched. With
  // no later mutation there would be no later post, and the tag would read as
  // absent from the whole load. Re-check a few times and post only if something
  // new has finished loading — inert markup that never loads costs no posts.
  var sentScriptCount = 0;
  var fetchRechecks = 0;
  var fetchRecheckTimer = null;
  function scheduleFetchRecheck() {
    if (fetchRecheckTimer || fetchRechecks >= 5) return;
    fetchRecheckTimer = setTimeout(function () {
      fetchRecheckTimer = null;
      fetchRechecks++;
      if (collectScripts().length > sentScriptCount) send();
      else if (awaitingFetch) scheduleFetchRecheck();
    }, 2000);
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
      if (desc) {
        sendFormSubmission(desc);
        beginFormWatch(control.form || null, desc);
      }
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

  // Must stay in step with IMPORTANT_FORM_ERROR_KEYWORDS in
  // apps/scripts/form_errors.py — the server filters again on the same phrases,
  // so anything only one side knows about is either dropped silently or never
  // sent. Every phrase here names a *delivery* failure; validation text ("this
  // field is required", "there was a problem with your submission") is the
  // visitor's problem, not the agency's, and is deliberately absent.
  var FAILURE_RE = /(submission failed|failed to send|failed to submit|could not be sent|could not send|unable to send|sending failed|was not sent|were not sent|error submitting|server error|internal error|error occurred|try again later|mail .{0,30}fail|smtp|\b50[0-4]\b)/i;

  // Contact Form 7 fires explicit DOM events — the highest-quality signal.
  document.addEventListener('wpcf7mailfailed', function (e) {
    var msg = (e.detail && e.detail.apiResponse && e.detail.apiResponse.message) || 'Mail send failed';
    var fid = e.detail && e.detail.contactFormId ? String(e.detail.contactFormId) : '';
    sendFormError('Contact Form 7', fid, msg);
  });

  // Generic path: after any submit, watch newly rendered text for ~20s.
  var watchForm = null;
  var watchDescriptor = null;
  var watchUntil = 0;
  var errObserver = null;

  // Torn down when the window closes rather than left attached for the life of
  // the page: this observes the whole document subtree including character data,
  // which on a single-page app or a long-lived tab is a permanent cost for a
  // callback that can no longer report anything.
  var watchTimer = null;

  function stopFormWatch() {
    watchTimer = null;
    if (!errObserver) return;
    try { errObserver.disconnect(); } catch (err) { }
    errObserver = null;
  }

  function beginFormWatch(form, desc) {
    watchForm = form || null;
    watchDescriptor = desc || null;
    watchUntil = Date.now() + 20000;
    // A second submit inside the window extends it rather than starting a
    // second observer.
    if (watchTimer) clearTimeout(watchTimer);
    watchTimer = setTimeout(stopFormWatch, 20500);
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
  }

  function checkErrorText(text) {
    if (!text || Date.now() > watchUntil) return;
    var t = String(text).trim();
    // Skip empty fragments and whole-page containers — status messages are short.
    if (t.length < 6 || t.length > 600) return;
    if (FAILURE_RE.test(t)) {
      var form = watchForm;
      var desc = watchDescriptor;
      var fid = desc ? (desc.form_id || desc.form_name || '') :
        (form ? (form.id || form.getAttribute('name') || '') : '');
      sendFormError(desc && desc.provider ? desc.provider : formSource(form), fid, t.slice(0, 500));
    }
  }

  function scanNode(node) {
    if (node.nodeType === 3) { checkErrorText(node.nodeValue); return; }
    if (node.nodeType === 1) checkErrorText(node.textContent);
  }

  document.addEventListener('submit', function (e) {
    watchForm = e.target && e.target.tagName === 'FORM' ? e.target : null;
    var desc = watchForm ? trackedFormFor(watchForm) : null;
    if (watchForm) sendFormSubmission(desc || null);
    beginFormWatch(watchForm, desc);
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
    } catch (_) { }
  });

  window.addEventListener('unhandledrejection', function (e) {
    try {
      var r = e && e.reason;
      var msg = r && r.message ? r.message : String(r);
      sendJsError('Unhandled promise rejection: ' + msg, '', null, null, r && r.stack);
    } catch (_) { }
  });

  // ── Heatmap interaction tracking ─────────────────────────────────────────
  // Passive collection of click / mouse-move / scroll behaviour, aggregated
  // client-side. Every raw position is normalised to a fraction of the page
  // (x = % of viewport width, y = % of full page height including scroll) and
  // binned into a 100x100 percentage grid, so a busy page becomes a handful of
  // cell rows instead of tens of thousands of events. Cells are buffered and
  // flushed to /ingest/heatmap/ on a timer and on page unload. Every handler
  // is wrapped so a failure here can never break the host page.

  var heatmapUrl = ingestUrl.replace(/\/ingest\/?$/, '/ingest/heatmap/');
  var heatmapCells = {};
  var heatmapCellEls = {};        // cell key -> best-effort element descriptor
  var heatmapTotalClicks = 0;
  var heatmapMaxVisible = 0;      // deepest page-fraction revealed, 0..1
  var heatmapSentMaxVisible = -1; // deepest fraction already reported
  var heatmapLastMove = 0;
  var heatmapLastScroll = 0;
  // Rage-click burst tracker: rapid, repeated clicks on the same cell signal a
  // frustrated user or a broken element, so we surface them as their own map.
  // Keyed by cell, value { count, last } of clicks within RAGE_WINDOW_MS.
  var heatmapRageBurst = {};
  var RAGE_WINDOW_MS = 2000;
  var RAGE_THRESHOLD = 3;         // identical-cell clicks inside the window
  var RAGE_MAX_TRACKED = 500;     // guard against pathological bursting pages

  // Both segment dimensions are properties of the *visit*, so they are resolved
  // once at load and reused for every flush. visitor_type especially must not be
  // recomputed: reading it is what marks the visitor as seen, so calling it
  // again mid-visit would report the same pageview as "returning".
  // (Function declarations hoist, so these run correctly despite being above
  // the definitions.)
  var heatmapVisitorBucket = heatmapVisitorType();
  var heatmapSourceBucket = heatmapSource();

  // ── opt-in gate ──────────────────────────────────────────────────────────
  // Behaviour analytics is enabled per site in Digivault, the way Hotjar is.
  // The authoritative gate is server-side (the ingest answers 204 and stores
  // nothing), because this file is cached and shared by every client and so
  // cannot be the thing that decides — but a disabled site should not be
  // paying for listeners and timers either, so the first 204 of a visit
  // disarms everything below and is remembered for the rest of the session.
  //
  // `data-heatmap="off"` on the script tag is a local override for anyone who
  // wants the tag itself to say no. There is deliberately no "on" value: the
  // dashboard toggle is the switch, and a page attribute that could turn
  // collection *on* would put that decision back in the client's markup.
  var HEATMAP_OFF_KEY = '_dv_hm_off_' + siteId;
  var heatmapOff = (el.getAttribute('data-heatmap') || '').toLowerCase() === 'off';
  var heatmapTimer = null;
  if (!heatmapOff) {
    try {
      if (window.sessionStorage && sessionStorage.getItem(HEATMAP_OFF_KEY)) {
        heatmapOff = true;
      }
    } catch (err) { /* blocked storage — probe once per page instead */ }
  }

  function heatmapDisarm() {
    heatmapOff = true;
    heatmapCells = {};
    heatmapCellEls = {};
    heatmapRageBurst = {};
    heatmapTotalClicks = 0;
    if (heatmapTimer) { clearTimeout(heatmapTimer); heatmapTimer = null; }
    try {
      if (window.sessionStorage) sessionStorage.setItem(HEATMAP_OFF_KEY, '1');
    } catch (err) { }
  }

  // The server said "stop" (collection off) or "this site is gone". Anything
  // else — a 5xx, a throttle, a network blip — is transient and must not
  // disarm, or one bad minute would switch a customer's heatmap off until
  // every visitor's session expired.
  function heatmapOnStatus(status) {
    if (status === 204 || status === 404) heatmapDisarm();
  }

  function heatmapDevice() {
    var touch = ('ontouchstart' in window) ||
      (navigator.maxTouchPoints && navigator.maxTouchPoints > 0);
    return (touch && (window.innerWidth || 1024) < 1025) ? 'mobile' : 'desktop';
  }

  // Full document height in CSS pixels. Every normalised y is a fraction of
  // this, so the dashboard needs it too: without it the overlay has no idea
  // what aspect ratio to draw at and has to ask a human to guess with a slider.
  // Reported alongside viewport_width on every flush.
  function heatmapPageHeight() {
    var d = document.documentElement;
    var b = document.body;
    return Math.max(
      (d ? d.scrollHeight : 0), (d ? d.offsetHeight : 0),
      (b ? b.scrollHeight : 0), (b ? b.offsetHeight : 0),
      window.innerHeight || 0,
      1
    );
  }

  function heatmapScrollTop() {
    return window.scrollY || window.pageYOffset ||
      (document.documentElement ? document.documentElement.scrollTop : 0) || 0;
  }

  function heatmapCoords(clientX, clientY) {
    var vw = window.innerWidth || 1;
    var docH = heatmapPageHeight();
    var sc = heatmapScrollTop();
    var x = Math.min(100, Math.max(0, Math.round(clientX / vw * 100)));
    var y = Math.min(100, Math.max(0, Math.round((clientY + sc) / docH * 100)));
    return { x: x, y: y };
  }

  function heatmapVisibleFraction() {
    var docH = heatmapPageHeight();
    if (docH <= 0) return 0;
    var visibleBottom = heatmapScrollTop() + (window.innerHeight || 1);
    return Math.min(1, visibleBottom / docH);
  }

  // Returning visitors are those we have seen on this site before. A first-party
  // localStorage flag is enough — this never leaves the origin and carries no
  // identifier, it is a single boolean, so it needs no consent banner of its own.
  function heatmapVisitorType() {
    try {
      var KEY = '_dv_seen';
      if (window.localStorage && localStorage.getItem(KEY)) return 'returning';
      if (window.localStorage) localStorage.setItem(KEY, '1');
    } catch (err) { /* private mode / blocked storage — treat as new */ }
    return 'new';
  }

  // Traffic source bucketed from the referrer, matching HeatmapActivity.Source.
  // An explicit utm_medium wins over the referrer host: an emailed link often
  // arrives with no referrer at all and would otherwise read as "direct".
  var SOCIAL_HOSTS = /(facebook|instagram|twitter|x\.com|linkedin|pinterest|reddit|tiktok|youtube|t\.co|whatsapp|telegram)\./i;
  var SEARCH_HOSTS = /(google|bing|yahoo|duckduckgo|yandex|baidu|ecosia|brave)\./i;

  function heatmapSource() {
    try {
      var medium = '';
      try {
        medium = (new URLSearchParams(window.location.search).get('utm_medium') || '').toLowerCase();
      } catch (err) { /* no URLSearchParams — fall through to the referrer */ }
      if (medium) {
        if (medium.indexOf('email') > -1 || medium === 'newsletter') return 'email';
        if (medium.indexOf('social') > -1 || medium === 'paid_social') return 'social';
        if (medium === 'organic') return 'organic';
        if (medium === 'referral') return 'referral';
      }
      var ref = document.referrer || '';
      if (!ref) return 'direct';
      var host = '';
      try { host = new URL(ref).hostname; } catch (err) { return 'direct'; }
      if (!host) return 'direct';
      // Same-site navigation is not a new source — keep the visit "direct"
      // rather than reporting every internal click-through as a referral.
      if (host.replace(/^www\./, '') === location.hostname.replace(/^www\./, '')) {
        return 'direct';
      }
      if (SOCIAL_HOSTS.test(host)) return 'social';
      if (SEARCH_HOSTS.test(host)) return 'organic';
      return 'referral';
    } catch (err) {
      return 'direct';
    }
  }

  function heatmapAdd(kind, x, y, el) {
    var k = kind + '|' + x + '|' + y;
    heatmapCells[k] = (heatmapCells[k] || 0) + 1;
    if (el) heatmapCellEls[k] = el;
  }

  // A short, stable-ish descriptor for the element at a clicked position, so a
  // hotspot can be attributed to e.g. `button#add-to-cart "Buy now"`. Prefer an
  // explicit id over tag/classes; body-level clicks are noise and return ''.
  function heatmapElementText(el) {
    try {
      var t;
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
        t = el.getAttribute('placeholder') || el.getAttribute('aria-label') || '';
      } else if (el.tagName === 'IMG') {
        t = el.getAttribute('alt') || '';
      } else {
        t = (el.textContent || '').trim().replace(/\s+/g, ' ');
      }
      return t ? t.slice(0, 28) : '';
    } catch (err) { return ''; }
  }

  function heatmapElementTag(el) {
    try {
      if (!el || !el.tagName) return '';
      if (el === document || el === document.body || el === document.documentElement) return '';
      var out = el.tagName.toLowerCase();
      if (el.id) out += '#' + el.id;
      if (el.className && typeof el.className === 'string') {
        var cls = el.className.trim().split(/\s+/).slice(0, 2).join('.');
        if (cls) out += '.' + cls;
      }
      var txt = heatmapElementText(el);
      if (txt) out += ' "' + txt + '"';
      return out.length > 120 ? out.slice(0, 117) + '...' : out;
    } catch (err) { return ''; }
  }

  // Per-visit scroll reach: 1 for every depth band this visit actually revealed,
  // absent for the rest. It is deliberately binary — the *share* of visitors who
  // got this far is a property of the population, not of one visit, so it can
  // only be computed server-side by averaging these across visits.
  //
  // This used to write `maxVisible` into every reached bucket, which made the
  // 5% band and the 80% band report the identical number. The dashboard renders
  // the histogram as a gradient, so a flat histogram painted a single flat
  // colour and the scroll map could never show a drop-off.
  function heatmapBuildHistogram(maxVisible) {
    var h = {};
    for (var b = 5; b <= 100; b += 5) {
      if (maxVisible >= b / 100) h['' + b] = 1;
    }
    return h;
  }

  function heatmapSend(final) {
    if (heatmapOff) return;
    var keys = Object.keys(heatmapCells);
    var cells = [];
    // Cap the number of cells per payload defensively — the 100x100 grid means
    // a page can never legitimately fill more than a few thousand.
    var cap = Math.min(keys.length, 3000);
    for (var i = 0; i < cap; i++) {
      var parts = keys[i].split('|');
      cells.push({
        kind: parts[0],
        x: parseInt(parts[1], 10),
        y: parseInt(parts[2], 10),
        count: heatmapCells[keys[i]],
        element: heatmapCellEls[keys[i]] || ''
      });
    }
    // On the final flush of a silent page (no clicks/moves/scroll) still send,
    // so the page appears in the dashboard and counts one visit + scroll depth.
    // Otherwise skip a flush that would tell the server nothing it has not
    // already been told: no new cells, no new clicks, and no deeper scroll than
    // the last post reported. Now that the timer actually repeats, without this
    // an idle open tab would post an identical payload every two minutes for as
    // long as it stayed open.
    if (
      !final && cells.length === 0 && heatmapTotalClicks === 0 &&
      heatmapMaxVisible <= heatmapSentMaxVisible
    ) {
      heatmapSchedule();
      return;
    }
    heatmapSentMaxVisible = heatmapMaxVisible;
    var payload = JSON.stringify({
      site_id: siteId,
      page_url: window.location.href,
      device: heatmapDevice(),
      visitor_type: heatmapVisitorBucket,
      source: heatmapSourceBucket,
      user_agent: navigator.userAgent,
      viewport_width: window.innerWidth || 0,
      // Lets the dashboard draw the overlay at the page's real aspect ratio
      // instead of asking the operator to guess it.
      page_height: heatmapPageHeight(),
      final: !!final,
      total_clicks: heatmapTotalClicks,
      max_scroll_percent: Math.round(heatmapMaxVisible * 100),
      scroll_histogram: heatmapBuildHistogram(heatmapMaxVisible),
      cells: cells
    });
    // Reset the per-flush counters that are incremental: cells and clicks are
    // handed off per flush. Scroll depth is monotonic within a session, so
    // heatmapMaxVisible is kept so the final flush reports the true peak.
    heatmapTotalClicks = 0;
    heatmapCells = {};
    heatmapCellEls = {};
    try {
      post(heatmapUrl, payload, heatmapOnStatus);
    } catch (err) { /* never break the host page */ }
    // Keep the timer running. This used to reschedule only on the early-return
    // path above, so the *first* flush that actually carried data was also the
    // last: everything a visitor did after their first fifteen seconds sat in
    // the buffer until unload, and a session ended by closing the laptop or by
    // a browser that skips `pagehide` lost all of it. A long read reported one
    // burst of activity at the top of the page and nothing below the fold.
    if (!final) heatmapSchedule();
  }

  // Periodic flush keeps near-real-time data flowing without waiting for page
  // unload. The interval widens as a visit goes on — most sessions are short,
  // so the early flushes are the ones that matter, and a reader who stays for
  // twenty minutes should not cost forty posts.
  var HEATMAP_FLUSH_MIN_MS = 15000;
  var HEATMAP_FLUSH_MAX_MS = 120000;
  var heatmapFlushDelay = HEATMAP_FLUSH_MIN_MS;

  function heatmapSchedule() {
    if (heatmapOff) return;
    if (heatmapTimer) clearTimeout(heatmapTimer);
    heatmapTimer = setTimeout(function () {
      heatmapTimer = null;
      heatmapSend(false);
    }, heatmapFlushDelay);
    heatmapFlushDelay = Math.min(heatmapFlushDelay * 2, HEATMAP_FLUSH_MAX_MS);
  }

  // The handlers below all guard on `heatmapOff` because a disarm can arrive
  // mid-visit, but a site already known to be off skips *registration* too:
  // a capturing mousemove listener that only ever early-returns is still a
  // capturing mousemove listener on someone else's page.
  if (heatmapOff) return;

  // Clicks (also covers taps on touch devices). Beyond counting every click,
  // we watch for rage bursts — the same cell hit RAGE_THRESHOLD+ times inside
  // RAGE_WINDOW_MS — and record those as their own 'rage' cells so the map can
  // spotlight the spots where visitors clearly got stuck or frustrated.
  document.addEventListener('click', function (e) {
    try {
      if (heatmapOff) return;
      heatmapTotalClicks++;
      var c = heatmapCoords(e.clientX, e.clientY);
      var elTag = heatmapElementTag(e.target);
      heatmapAdd('click', c.x, c.y, elTag);
      var key = c.x + '|' + c.y;
      var now = Date.now();
      var burst = heatmapRageBurst[key];
      if (burst && (now - burst.last <= RAGE_WINDOW_MS)) {
        burst.count++;
        burst.last = now;
        if (burst.count >= RAGE_THRESHOLD) {
          heatmapAdd('rage', c.x, c.y, elTag);
          // Reset the burst so sustained clicking counts bursts, not clicks.
          heatmapRageBurst[key] = { count: 0, last: now };
        }
      } else {
        heatmapRageBurst[key] = { count: 1, last: now };
      }
      // Bound the tracker: on a pathological page drop the whole state rather
      // than risk unbounded growth (a burst lost here is harmless).
      var tracked = 0;
      for (var k in heatmapRageBurst) { tracked++; if (tracked > RAGE_MAX_TRACKED) break; }
      if (tracked > RAGE_MAX_TRACKED) heatmapRageBurst = {};
    } catch (err) { }
  }, true);

  // Mouse movement, sampled ~every 120ms (Hotjar samples at 100ms). Desktop
  // only in practice — touch devices have no mousemove.
  document.addEventListener('mousemove', function (e) {
    try {
      if (heatmapOff) return;
      var now = Date.now();
      if (now - heatmapLastMove < 120) return;
      heatmapLastMove = now;
      var c = heatmapCoords(e.clientX, e.clientY);
      heatmapAdd('move', c.x, c.y);
    } catch (err) { }
  }, true);

  // Scroll: keep the deepest page-fraction revealed.
  function heatmapOnScroll() {
    try {
      if (heatmapOff) return;
      var now = Date.now();
      if (now - heatmapLastScroll < 300) return;
      heatmapLastScroll = now;
      var vf = heatmapVisibleFraction();
      if (vf > heatmapMaxVisible) heatmapMaxVisible = vf;
    } catch (err) { }
  }
  window.addEventListener('scroll', heatmapOnScroll, true);
  window.addEventListener('resize', heatmapOnScroll, true);
  // One immediate sample in case the page loads pre-scrolled (e.g. deep links).
  setTimeout(function () { heatmapOnScroll(); }, 2500);

  // Periodic flush for freshness. Also the probe that learns whether this site
  // has behaviour analytics switched on at all — a disabled site gets one small
  // 204 in its first fifteen seconds and then goes quiet for the whole session.
  heatmapSchedule();

  // Final flush on unload / backgrounding, carrying remaining cells and the
  // visit count. bfcache-safe: reload after a back/forward does not lose data.
  //
  // `final` is what increments the page's visit counter, so it may be sent at
  // most once per pageview — but a *flush* has to be able to happen every time
  // the tab is hidden. Conflating the two meant the first tab-away ended
  // collection for good: a visitor who checked their email and came back read
  // the rest of the page with every click going nowhere, and a page opened in
  // a background tab counted its visit before it was ever looked at.
  var heatmapVisitCounted = false;
  function heatmapFlushFinal() {
    if (heatmapOff) return;
    var countThis = !heatmapVisitCounted;
    heatmapVisitCounted = true;
    heatmapSend(countThis);
  }
  window.addEventListener('pagehide', heatmapFlushFinal);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
      heatmapFlushFinal();
    } else {
      // Back in the foreground: restart the timer the flush above consumed,
      // from the short end of the backoff since this is effectively a fresh
      // stretch of reading.
      heatmapFlushDelay = HEATMAP_FLUSH_MIN_MS;
      heatmapSchedule();
    }
  });

  // ── nothing below this line ──────────────────────────────────────────────
  // The heatmap section ends the snippet, and it opens with a `return` guard
  // for sites that have collection switched off. Anything appended here would
  // be skipped on those sites without a word — put new sections above the
  // "Heatmap interaction tracking" banner instead.

})();
