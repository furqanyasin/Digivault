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

  function collectForms() {
    var forms = document.querySelectorAll('form');
    var result = [];
    for (var i = 0; i < forms.length; i++) {
      var f = forms[i];
      var fieldList = [];
      var inputs = f.querySelectorAll('input, textarea, select');
      for (var j = 0; j < inputs.length; j++) {
        var inp = inputs[j];
        var t = inp.type || 'text';
        if (t === 'hidden' || t === 'submit' || t === 'button' || t === 'reset' || t === 'image') continue;
        var labelText = '';
        if (inp.id) {
          var lbl = document.querySelector('label[for="' + inp.id + '"]');
          if (lbl) labelText = (lbl.textContent || '').trim();
        }
        fieldList.push({
          name: inp.name || '',
          type: inp.tagName.toLowerCase() === 'textarea' ? 'textarea' :
                inp.tagName.toLowerCase() === 'select' ? 'select' : t,
          label: labelText,
          required: inp.required || false
        });
      }
      result.push({
        form_id: f.id || '',
        form_name: f.getAttribute('name') || '',
        form_action: f.action || '',
        form_method: (f.method || 'post').toLowerCase(),
        fields: fieldList
      });
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
      snippet_version: '1.3'
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

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(send, 0);
  } else {
    document.addEventListener('DOMContentLoaded', send);
  }
})();
