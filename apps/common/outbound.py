"""One HTTP client for every server-side fetch of a customer's own site.

Digivault reaches out to client origins from five places — the uptime monitor,
the SEO checker, the homepage scan, the snippet verifier and the WordPress form
sync — and every one of them leaves from the platform's single public IP. Before
this module they each rolled their own headers, none of them shared a rate
budget, and none honoured a 429. The SEO checker alone fetches up to fifteen
pages back-to-back, which reads to any WAF exactly like a scanner sweep. That is
how the IP gets challenged, then blocked, then blacklisted — at which point the
monitor starts reporting healthy sites as down.

Three responsibilities live here so that no caller can forget them:

**Identity.** One honest, stable user-agent, following the shape UptimeRobot
uses. We deliberately do *not* impersonate Chrome: from a single IP a spoofed
browser is caught on TLS fingerprint anyway, it gets that IP banned with no
route to appeal, and it permanently disqualifies us from Cloudflare's Verified
Bots programme. These are our own clients' sites — being allowlistable is worth
far more to us than being sneaky.

**A budget.** A per-host token bucket, keyed on the registrable domain so
``example.com`` and ``www.example.com`` cannot be used to double the rate. It
fails *open*: if Redis is unreachable, monitoring continues rather than stopping.

**Restraint.** A 429 or a ``Retry-After`` puts the host in cooldown; repeated
403s escalate that cooldown exponentially. Continuing to poll a host that has
just told us to back off is the specific behaviour that turns a rate-limit into
a ban.
"""
from __future__ import annotations

import logging
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache

from apps.common.ssrf import assert_public_url

logger = logging.getLogger(__name__)

# ── identity ──────────────────────────────────────────────────────────────────

# The "Mozilla/5.0 (compatible; ...)" prefix is not an impersonation — it is the
# convention every well-behaved crawler follows, and it gets us past UA sniffers
# that reject anything not starting with "Mozilla". The +URL is the part that
# matters: it gives a site owner staring at their firewall log something to look
# up, and it is what a WAF vendor needs in order to allowlist us.
#
# The product token is "Digivault-Uptime", with "Digivault-Monitor" kept as a
# second token. SiteGround's firewall blocks the exact form
# "compatible; Digivault-Monitor/1.0" on every path (a 403 page, or its 202
# bot challenge) while letting "compatible; Digivault-Uptime/1.0" through — so
# every SiteGround-hosted client read "blocked". "Digivault-Monitor" stays in
# the string because client Cloudflare rules allowlist `user_agent contains
# "Digivault-Monitor"`, and dropping it would block those sites instead.
# Still honest: it names us, names no browser, and links to /bot.
#
# MONITOR_USER_AGENT overrides it from the environment, so if a host starts
# blocking this string too, it can be changed without a release.
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; Digivault-Uptime/1.0; Digivault-Monitor; "
    "+https://digivault.digilatics.co/bot)"
)
USER_AGENT = getattr(settings, "MONITOR_USER_AGENT", "") or _DEFAULT_USER_AGENT

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    # A request with no Accept at all reads as a bot to every bot-management
    # edge, so we send a real one even though we mostly discard the body.
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── errors ────────────────────────────────────────────────────────────────────

class OutboundError(Exception):
    """Base for refusals raised before any network call is made."""


class RateLimitedError(OutboundError):
    """Our own per-host budget declined this request."""


class HostCoolingDownError(OutboundError):
    """The host asked us to back off and the cooldown has not elapsed."""


# ── budget / backoff tuning ───────────────────────────────────────────────────

DEFAULT_MIN_INTERVAL_SECONDS = 20
DEFAULT_MAX_PER_HOUR = 60
BASE_COOLDOWN_SECONDS = 60
MAX_COOLDOWN_SECONDS = 3600


def _setting(name: str, default):
    return getattr(settings, name, default)


# ── host keying ───────────────────────────────────────────────────────────────

def registrable_host(url: str) -> str:
    """Normalise a URL to the key its rate budget is held under.

    Collapses scheme, port, case and a leading ``www.`` so that a caller cannot
    accidentally (or deliberately) double a host's budget by varying the form of
    the URL. Deeper subdomains stay distinct — ``shop.example.com`` really is a
    different origin, often on different infrastructure.
    """
    host = (urlsplit(url).hostname or url).lower()
    if host.startswith("www."):
        host = host[4:]
    return host


# ── block identification ──────────────────────────────────────────────────────

# Bodies a bot-protection edge or WAF serves in place of the real page. Matching
# any of these means we did not see the customer's HTML, so we cannot conclude
# anything about whether their site is healthy.
BLOCK_PAGE_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "cf_chl_opt",
    "checking your browser",
    "enable javascript and cookies to continue",
    "attention required! | cloudflare",
    "ddos protection by",
    "403 - forbidden",
    "403 forbidden",
    "access denied",
    "request blocked",
    "you have been blocked",
    "web application firewall",
    "mod_security",
    "are you a human",
    "captcha",
)

# Real pages are bigger than this. Interstitials and error stubs are not.
MIN_PLAUSIBLE_PAGE_BYTES = 1024

# Header fingerprints, checked first because they are unambiguous. Each entry is
# (header name, substring to look for in its lowercased value, vendor). An empty
# substring matches on the header's mere presence.
_HEADER_FINGERPRINTS: tuple[tuple[str, str, str], ...] = (
    ("cf-mitigated", "challenge", "Cloudflare"),
    ("x-sucuri-block", "", "Sucuri"),
    ("x-imunify360-request-id", "", "Imunify360"),
    ("x-amzn-waf-action", "", "AWS WAF"),
    ("x-iinfo", "", "Imperva"),
    ("x-cdn", "incapsula", "Imperva"),
    ("server", "sucuri", "Sucuri"),
    ("server", "mod_security", "ModSecurity"),
    ("server", "cloudflare", "Cloudflare"),
    ("server", "awselb", "AWS WAF"),
    ("server", "akamaighost", "Akamai"),
    ("server", "litespeed", "LiteSpeed"),
)

# SiteGround puts the same `host-header` value on every response it serves, real
# pages included, and its anti-bot answers an unrecognised client with a `202`
# challenge page (a meta refresh to `/.well-known/sgcaptcha/`) instead of the
# site. Eight client sites read "degraded — Got 202, expected 200" with 0%
# uptime for exactly that reason. Because the header is on everything, it only
# names a block on the codes SiteGround blocks with: a SiteGround 503 is the
# origin overloaded, and must stay a real outage.
_SITEGROUND_HOST_HEADER = "8441280b0c35cbc1147f8ba998a563a7"
_SITEGROUND_BLOCK_CODES = frozenset({202, 403, 429})

# Body fingerprints for WAFs that add no distinguishing header — the WordPress
# plugin firewalls, mostly, which run inside PHP and cannot set edge headers.
_BODY_FINGERPRINTS: tuple[tuple[str, str], ...] = (
    ("wordfence", "Wordfence"),
    ("generated by wordfence", "Wordfence"),
    ("mod_security", "ModSecurity"),
    ("imunify360", "Imunify360"),
    ("sucuri website firewall", "Sucuri"),
    ("sgcaptcha", "SiteGround"),
    ("cloudflare", "Cloudflare"),
)

# Only these codes can be a block. A 500 is the origin failing and must never be
# excused; a 404 is a real missing page. 202 is a challenge interstitial
# (SiteGround, AWS WAF) — "accepted, come back with a browser" — and is only
# ever called a block on a positive fingerprint, never on page size alone.
_BLOCKABLE_CODES = frozenset({202, 401, 403, 406, 429, 503})


def looks_like_block_page(html: str) -> bool:
    """True when the body is an interstitial rather than the site's real page."""
    head = (html or "")[:8192].lower()
    if any(marker in head for marker in BLOCK_PAGE_MARKERS):
        return True
    return len(html or "") < MIN_PLAUSIBLE_PAGE_BYTES


def identify_block(status_code: int, headers: Mapping[str, str], body: str) -> str:
    """Name the WAF that blocked us, or return "" if this is not a block.

    Deliberately conservative in both directions. It refuses to look at 2xx/5xx
    at all — a Cloudflare-fronted site serves its real pages with
    ``server: cloudflare`` too, and a 500 behind Cloudflare is a genuine origin
    outage. And an unattributable 403 stays unattributed: a site that simply
    forbids us is down as far as we can tell, and blanket-excusing every 403
    would let a real misconfiguration hide forever behind a "blocked" badge.
    """
    if status_code not in _BLOCKABLE_CODES:
        return ""

    lowered = {str(k).lower(): str(v).lower() for k, v in (headers or {}).items()}
    if (
        status_code in _SITEGROUND_BLOCK_CODES
        and lowered.get("host-header") == _SITEGROUND_HOST_HEADER
    ) or "sg-captcha" in lowered or "sgcaptcha" in (body or "")[:8192].lower():
        return "SiteGround"
    for header, needle, vendor in _HEADER_FINGERPRINTS:
        value = lowered.get(header)
        if value is None:
            continue
        if not needle or needle in value:
            return vendor

    head = (body or "")[:8192].lower()
    for needle, vendor in _BODY_FINGERPRINTS:
        if needle in head:
            return vendor

    # No vendor named, but the body is plainly an interstitial rather than a
    # page. Worth flagging as a block without claiming to know who did it — but
    # not for a 2xx, where a short body is not evidence of anything.
    if status_code >= 400 and body and looks_like_block_page(body):
        return "an unidentified firewall"

    return ""


# ── per-host budget ───────────────────────────────────────────────────────────

def consume_budget(host: str) -> bool:
    """Take one token for `host`. False means the caller must not fetch.

    Fails open. If the cache is unreachable we allow the request: a monitoring
    platform that stops monitoring because Redis blinked is worse than one that
    briefly polls a little faster than intended.
    """
    min_interval = _setting("OUTBOUND_MIN_INTERVAL_SECONDS", DEFAULT_MIN_INTERVAL_SECONDS)
    max_per_hour = _setting("OUTBOUND_MAX_PER_HOUR", DEFAULT_MAX_PER_HOUR)
    now = time.time()

    try:
        if min_interval:
            last = cache.get(f"outbound:last:{host}")
            if last is not None and (now - float(last)) < min_interval:
                return False

        hour_key = f"outbound:count:{host}:{int(now // 3600)}"
        used = cache.get(hour_key) or 0
        if max_per_hour and used >= max_per_hour:
            return False

        cache.set(f"outbound:last:{host}", now, timeout=max(int(min_interval) * 2, 60))
        cache.set(hour_key, int(used) + 1, timeout=3600)
    except Exception:
        logger.warning("outbound: budget check failed for %s, allowing", host, exc_info=True)
        return True

    return True


# ── per-host backoff ──────────────────────────────────────────────────────────

def _cool_key(host: str) -> str:
    return f"outbound:cool:{host}"


def _strikes_key(host: str) -> str:
    return f"outbound:strikes:{host}"


def cooldown_remaining(host: str) -> int:
    """Seconds left before `host` may be contacted again. 0 means go ahead."""
    try:
        until = cache.get(_cool_key(host))
    except Exception:
        return 0
    if not until:
        return 0
    return max(0, int(float(until) - time.time()))


def _set_cooldown(host: str, seconds: int) -> None:
    seconds = min(int(seconds), MAX_COOLDOWN_SECONDS)
    try:
        cache.set(_cool_key(host), time.time() + seconds, timeout=seconds + 60)
    except Exception:
        logger.warning("outbound: could not set cooldown for %s", host, exc_info=True)


def note_rate_limited(host: str, retry_after: int | None = None) -> None:
    """The host returned 429/503. Respect its Retry-After if it gave us one."""
    _set_cooldown(host, retry_after or BASE_COOLDOWN_SECONDS)


def note_blocked(host: str) -> None:
    """The host blocked us. Escalate the cooldown so we stop making it worse."""
    try:
        strikes = int(cache.get(_strikes_key(host)) or 0) + 1
        cache.set(_strikes_key(host), strikes, timeout=MAX_COOLDOWN_SECONDS)
    except Exception:
        strikes = 1
    _set_cooldown(host, BASE_COOLDOWN_SECONDS * (2 ** (strikes - 1)))


def note_success(host: str) -> None:
    """The host answered normally. Forget the strikes and lift any cooldown."""
    try:
        cache.delete(_cool_key(host))
        cache.delete(_strikes_key(host))
    except Exception:
        pass


# ── fetch ─────────────────────────────────────────────────────────────────────

class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-run the SSRF guard on every redirect hop.

    Validating only the URL we were handed is not a guard at all: a perfectly
    public host can answer 302 with ``Location: http://169.254.169.254/`` (cloud
    metadata) or ``http://127.0.0.1:8000/`` (this very API), and urllib follows
    it without asking anyone. The attacker never needs to supply an internal URL
    — they only need to control a public one that points at an internal one.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Built once. `urlopen`'s default opener has an unguarded redirect handler, so
# every request in this module goes through ours instead.
_OPENER = urllib.request.build_opener(_GuardedRedirectHandler)


def _opener() -> urllib.request.OpenerDirector:
    return _OPENER


def _acquire(host: str, wait_up_to: int) -> bool:
    """Take a token, optionally waiting out the spacing window for it.

    Burst callers — the SEO checker walks fifteen pages of one host — must pace
    rather than fail. Failing fourteen of those fifteen would report a healthy
    site as having no robots.txt and no sitemap, which is a worse lie than the
    delay is a cost. Waiting turns the same fifteen requests into polite,
    spaced-out traffic, which is the whole point of the budget.
    """
    if consume_budget(host):
        return True
    if wait_up_to <= 0:
        return False

    deadline = time.monotonic() + wait_up_to
    while time.monotonic() < deadline:
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        if consume_budget(host):
            return True
    return False


@dataclass
class FetchResult:
    status_code: int
    body: str
    headers: dict[str, str]
    elapsed_ms: int
    final_url: str
    #: The response was longer than `read_bytes`, so `body` is a prefix of it.
    #: A caller parsing JSON must treat this as a failed read: a half-read
    #: Elementor payload is indistinguishable from a page with no form unless
    #: it is flagged here.
    truncated: bool = False

    @property
    def blocked_by(self) -> str:
        return identify_block(self.status_code, self.headers, self.body)


    #: The requested name did not answer and its ``www.`` twin did, so this
    #: result came from `final_url`'s host rather than the one asked for.
    host_fallback: bool = False


# ── www twin fallback ─────────────────────────────────────────────────────────

# Second-level labels under which a country TLD sells its registrations, so
# that ``example.co.uk`` is recognised as an apex and not as a subdomain.
_SECOND_LEVEL_LABELS = frozenset({"co", "com", "net", "org", "gov", "edu", "ac"})


def _is_apex(host: str) -> bool:
    labels = host.split(".")
    if len(labels) == 2:
        return True
    return (
        len(labels) == 3
        and len(labels[2]) == 2
        and labels[1] in _SECOND_LEVEL_LABELS
    )


def sibling_url(url: str) -> str | None:
    """The same URL on the ``www.``-toggled host, or None if there is no twin.

    Only an apex and its ``www.`` form are twins. ``shop.example.com`` has none:
    guessing ``www.shop.example.com`` would be a request to a name nobody set up.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host or host.replace(".", "").isdigit():
        return None
    if host.startswith("www."):
        twin = host[4:]
        if not _is_apex(twin):
            return None
    elif _is_apex(host):
        twin = f"www.{host}"
    else:
        return None
    netloc = twin if parts.port is None else f"{twin}:{parts.port}"
    return parts._replace(netloc=netloc).geturl()


def _is_name_failure(exc: BaseException) -> bool:
    """True when the error says this *name* is not served, not that the site is down.

    The common case is a site set up on only one of ``example.com`` and
    ``www.example.com``: Cloudflare answers a TLS handshake for a name it holds no
    certificate for with alert 40, the other name has no DNS record, or nothing
    listens there. Visitors never notice because they arrive on the working name.
    Timeouts and resets are deliberately not in this set. They say nothing about
    the name, and retrying one would double a check's worst-case duration.
    """
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return isinstance(
        reason, (ssl.SSLError, socket.gaierror, ConnectionRefusedError)
    )


def fetch(
    url: str,
    *,
    method: str = "GET",
    timeout: int = 30,
    extra_headers: Mapping[str, str] | None = None,
    bypass_budget: bool = False,
    wait_up_to: int = 0,
    read_bytes: int = 65536,
    data: bytes | None = None,
) -> FetchResult:
    """Fetch `url` under the shared identity, budget and backoff rules.

    Raises ``BlockedURLError`` (SSRF guard), ``HostCoolingDownError`` or
    ``RateLimitedError`` *before* touching the network. HTTP error statuses are
    returned as a ``FetchResult``, not raised — a 403 is an answer, and the
    caller needs the headers to work out who sent it.

    `bypass_budget` exists for uptime confirmation re-checks: three requests
    inside a minute during a suspected outage is proportionate, and it is
    bounded at three. It is also how callers reach a *third-party* API rather
    than a customer origin — a Slack webhook is not something the per-host
    budget should pace — while still inheriting the SSRF guard on every
    redirect hop, which is the part none of them can be allowed to skip.

    `data` sends a request body. It exists so that a caller with a POST to make
    has no reason to reach for `urllib`/`requests` directly; every such caller
    that did lost the redirect guard along with everything else.
    """
    assert_public_url(url)
    host = registrable_host(url)

    cooling = cooldown_remaining(host)
    if cooling and not bypass_budget:
        raise HostCoolingDownError(f"{host} is in backoff for another {cooling}s")

    if not bypass_budget and not _acquire(host, wait_up_to):
        raise RateLimitedError(f"per-host budget exhausted for {host}")

    headers = dict(DEFAULT_HEADERS)
    if extra_headers:
        headers.update(extra_headers)

    try:
        result = _open(url, method, headers, data, timeout, read_bytes)
    except urllib.error.URLError as exc:
        # One name of the pair not being served is a setup quirk of the site,
        # not an outage: try the twin before reporting anything. Only for reads,
        # and only once. A POST is never replayed to a host nobody named. The
        # twin shares this host's budget key, so this spends no second token.
        twin = sibling_url(url) if method.upper() in ("GET", "HEAD") else None
        if twin is None or not _is_name_failure(exc):
            raise
        assert_public_url(twin)
        try:
            result = _open(twin, method, headers, data, timeout, read_bytes)
        except urllib.error.URLError:
            raise exc from None
        result.host_fallback = True
        logger.info("outbound: %s not served, answered on %s", url, twin)

    _record_outcome(host, result)
    return result


def _open(url, method, headers, data, timeout, read_bytes) -> FetchResult:
    req = urllib.request.Request(url, data=data, method=method.upper())
    for key, value in headers.items():
        req.add_header(key, value)

    start = time.monotonic()
    try:
        with _opener().open(req, timeout=timeout) as resp:
            # One byte past the cap, so a body sitting exactly on the limit is
            # not misreported as truncated.
            raw = resp.read(read_bytes + 1)
            result = FetchResult(
                status_code=getattr(resp, "status", None) or resp.getcode(),
                body=raw[:read_bytes].decode("utf-8", errors="ignore"),
                headers={k.lower(): v for k, v in resp.headers.items()},
                elapsed_ms=int((time.monotonic() - start) * 1000),
                final_url=resp.geturl(),
                truncated=len(raw) > read_bytes,
            )
    except urllib.error.HTTPError as exc:
        raw = b""
        try:
            raw = exc.read(read_bytes + 1)
        except Exception:
            pass
        result = FetchResult(
            status_code=exc.code,
            body=raw[:read_bytes].decode("utf-8", errors="ignore"),
            headers={k.lower(): v for k, v in (exc.headers or {}).items()},
            elapsed_ms=int((time.monotonic() - start) * 1000),
            final_url=url,
            truncated=len(raw) > read_bytes,
        )
    return result


def _record_outcome(host: str, result: FetchResult) -> None:
    """Feed the response back into the backoff state."""
    if result.status_code in (429, 503):
        retry_after = result.headers.get("retry-after")
        seconds = None
        if retry_after and str(retry_after).strip().isdigit():
            seconds = int(str(retry_after).strip())
        note_rate_limited(host, seconds)
        return

    if result.blocked_by:
        note_blocked(host)
        return

    if result.status_code < 400:
        note_success(host)


# ── Our own egress IP ─────────────────────────────────────────────────────────

#: Services that echo the caller's public IP as plain text. Tried in order.
_IP_ECHO_URLS = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
)
_EGRESS_CACHE_KEY = "outbound:egress_ips"
_EGRESS_CACHE_SECONDS = 6 * 60 * 60


def egress_ips() -> list[str]:
    """The public IP(s) our checks leave from — what a site owner allowlists.

    `MONITOR_EGRESS_IPS` wins when set. It never was in production, so every
    allowlist rule, the /bot page and every "blocked" message said "contact your
    agency for the current IP" — a dead end on exactly the screen meant to end
    one, and SiteGround (which only allowlists by ticket) cannot act on it. So
    when it is unset we ask an IP-echo service once and cache the answer: this
    runs on the same host the monitor's requests leave from.

    Never raises; an empty list means "unknown" and callers keep their fallback
    wording.
    """
    configured = [ip for ip in (getattr(settings, "MONITOR_EGRESS_IPS", None) or []) if ip]
    if configured:
        return list(configured)
    if not getattr(settings, "MONITOR_DETECT_EGRESS_IP", True):
        return []
    try:
        cached = cache.get(_EGRESS_CACHE_KEY)
    except Exception:  # noqa: BLE001 — cache down: detect without it
        cached = None
    if cached is not None:
        return list(cached)

    import ipaddress

    detected: list[str] = []
    for url in _IP_ECHO_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310 — fixed https URL
                text = resp.read(64).decode("ascii", "ignore").strip()
            ip = ipaddress.ip_address(text)
            if ip.is_global:
                detected = [str(ip)]
                break
        except Exception:  # noqa: BLE001 — try the next service
            continue
    try:
        # Cache a miss too, briefly, so a dead echo service is not retried on
        # every request that renders an allowlist rule.
        cache.set(_EGRESS_CACHE_KEY, detected, _EGRESS_CACHE_SECONDS if detected else 300)
    except Exception:  # noqa: BLE001
        pass
    return detected
