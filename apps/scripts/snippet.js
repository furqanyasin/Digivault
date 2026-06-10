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

  function isWpCore(src) {
    return src.indexOf('/wp-includes/') !== -1 || src.indexOf('/wp-admin/') !== -1;
  }

  function collectScripts() {
    var tags = document.querySelectorAll('script');
    var scripts = [];
    var seen = {};
    for (var i = 0; i < tags.length; i++) {
      var t = tags[i];
      var src = (t.src || '').trim();
      if (!src) continue;
      if (seen[src]) continue;
      if (isWpCore(src)) continue;
      seen[src] = true;
      var loc = 'unknown';
      if (document.head && document.head.contains(t)) loc = 'head';
      else if (document.body && document.body.contains(t)) loc = 'body';
      scripts.push({
        src: src,
        location: loc,
        is_async: t.async || false,
        is_defer: t.defer || false,
        is_inline: false
      });
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

  function collectForms() {
    var result = [];

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
      result.push({
        form_id: f.id || '',
        form_name: f.getAttribute('name') || '',
        form_action: f.action || '',
        form_method: (f.method || 'post').toLowerCase(),
        detection_type: 'native',
        provider: '',
        fields: fieldList
      });
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
      result.push({
        form_id: grp.container.id || '',
        form_name: (grp.container.getAttribute && grp.container.getAttribute('name')) || '',
        form_action: '',
        form_method: 'post',
        detection_type: 'dom',
        provider: '',
        fields: grp.fields
      });
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
      snippet_version: '1.5'
    });
    if (navigator.sendBeacon) {
      var blob = new Blob([payload], { type: 'application/json' });
      navigator.sendBeacon(ingestUrl, blob);
    } else {
      var xhr = new XMLHttpRequest();
      xhr.open('POST', ingestUrl, true);
      xhr.setRequestHeader('Content-Type', 'application/json');
      xhr.send(payload);
    }
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
  var reportedErrors = {};

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
    if (navigator.sendBeacon) {
      navigator.sendBeacon(formErrorsUrl, new Blob([payload], { type: 'application/json' }));
    } else {
      var xhr = new XMLHttpRequest();
      xhr.open('POST', formErrorsUrl, true);
      xhr.setRequestHeader('Content-Type', 'application/json');
      xhr.send(payload);
    }
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
})();
