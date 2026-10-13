"""A second opinion from Google when a firewall blocks our own checks.

Monitoring leaves from one IP, and plenty of hosts (SiteGround, Imunify360,
server firewalls) block it outright — the site then reads "blocked" forever:
no uptime, and no way to notice a real outage. Google's PageSpeed Insights API
loads a page from Google's own infrastructure, which those firewalls do not
block, and reports whether the document loaded and with what status.

So when our check is blocked, we ask Google — at most every
`_REQUEST_EVERY` per monitor, in the background, because a run takes 10–20s
and spends API quota (the PAGESPEED_API_KEY's 25k/day). Its answer, kept for
`_VERDICT_TTL`, stands in for ours:

- Google loaded it  → "up", with real uptime.
- Google could not  → "down", and the normal confirmation/alert path runs —
  today a blocked site can never alert, so a real outage went unnoticed.
- Anything unclear (quota, Google blocked too, a 4xx that may be a block) →
  no verdict; the monitor stays "blocked", exactly as before. A second opinion
  may only ever replace "blocked", never invent a status from nothing.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_REQUEST_EVERY = 30 * 60          # seconds between Google runs per monitor
_VERDICT_TTL = 45 * 60            # how long a verdict stands in for our check
_TIMEOUT = 120

#: Lighthouse runtime errors that mean the page itself could not be loaded.
_DOWN_ERRORS = {
    "FAILED_DOCUMENT_REQUEST", "ERRORED_DOCUMENT_REQUEST", "DNS_FAILURE",
    "NO_DOCUMENT_REQUEST", "PROTOCOL_TIMEOUT", "PAGE_HUNG",
    "INSECURE_DOCUMENT_REQUEST", "CHROME_INTERSTITIAL_ERROR",
}
#: Status codes that may be a firewall answering Google too — no verdict.
_INCONCLUSIVE_CODES = {401, 403, 407, 429}


def enabled() -> bool:
    return bool(getattr(settings, "MONITOR_SECOND_OPINION", True)) and bool(
        getattr(settings, "PAGESPEED_API_KEY", "")
    )


def _verdict_key(monitor_id) -> str:
    return f"monitor:second_opinion:{monitor_id}"


def _lock_key(monitor_id) -> str:
    return f"monitor:second_opinion:lock:{monitor_id}"


def ask_google(url: str) -> dict | None:
    """Google's view of `url`: {"status": "up"|"down", "message", "status_code"},
    or None when the answer would be a guess."""
    params = urllib.parse.urlencode({
        "url": url,
        "category": "seo",           # smallest category that includes http-status-code
        "strategy": "mobile",
        "key": settings.PAGESPEED_API_KEY,
    })
    try:
        with urllib.request.urlopen(f"{_PSI_URL}?{params}", timeout=_TIMEOUT) as resp:  # noqa: S310
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        # 429 = quota, 400 = Google refused the URL, 500 = Google's own fault.
        logger.info("second opinion for %s: PageSpeed answered HTTP %s", url, exc.code)
        return None
    except Exception:  # noqa: BLE001 — timeout, network, bad JSON
        logger.info("second opinion for %s: PageSpeed unreachable", url, exc_info=True)
        return None
    return parse(data)


def parse(data: dict) -> dict | None:
    """Turn a PageSpeed response into a verdict. Pure, for tests."""
    lr = (data or {}).get("lighthouseResult")
    if not lr:
        return None
    runtime = lr.get("runtimeError") or {}
    code = runtime.get("code")
    message = runtime.get("message", "")
    status_match = re.search(r"Status code: (\d{3})", message)
    status_code = int(status_match.group(1)) if status_match else None

    if code:
        if status_code in _INCONCLUSIVE_CODES:
            return None  # Google got a firewall page too
        if code in _DOWN_ERRORS:
            return {
                "status": "down",
                "status_code": status_code,
                "message": (
                    "Google could not load the site either"
                    + (f" (HTTP {status_code})" if status_code else f" ({code})")
                    + " — this is a real outage, not our IP being blocked."
                ),
            }
        return None

    audit = (lr.get("audits") or {}).get("http-status-code") or {}
    if audit.get("score") == 1:
        return {
            "status": "up",
            "status_code": 200,
            "message": "Up, checked by Google — our own checks are blocked by the site's firewall.",
        }
    return None


def fresh_verdict(monitor) -> dict | None:
    """A recent Google verdict for this monitor, if one is standing."""
    try:
        v = cache.get(_verdict_key(monitor.pk))
    except Exception:  # noqa: BLE001
        return None
    if v and time.time() - v.get("at", 0) < _VERDICT_TTL:
        return v
    return None


def request(monitor) -> bool:
    """Queue a Google check unless one ran (or is running) recently."""
    if not enabled():
        return False
    try:
        if not cache.add(_lock_key(monitor.pk), 1, _REQUEST_EVERY):
            return False
    except Exception:  # noqa: BLE001 — cache down: do not hammer Google
        return False
    from apps.monitors.tasks import google_second_opinion

    google_second_opinion.delay(str(monitor.pk))
    return True


def store(monitor_id, verdict: dict) -> None:
    try:
        cache.set(_verdict_key(monitor_id), {**verdict, "at": time.time()}, _VERDICT_TTL)
    except Exception:  # noqa: BLE001
        pass
