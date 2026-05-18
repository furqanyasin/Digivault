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

  function collectScripts() {
    var tags = document.querySelectorAll('script');
    var scripts = [];
    var seen = {};
    for (var i = 0; i < tags.length; i++) {
      var t = tags[i];
      var src = (t.src || '').trim();
      if (!src) continue;
      if (seen[src]) continue;
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

  function send() {
    var scripts = collectScripts();
    var payload = JSON.stringify({
      site_id: siteId,
      page_url: window.location.href,
      scripts: scripts,
      user_agent: navigator.userAgent,
      snippet_version: '1.1'
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
