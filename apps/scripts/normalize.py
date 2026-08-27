"""URL normalization — stable identity for scripts and pages.

WordPress and page builders append volatile cache-buster query params
(?ver=6.4.2, ?nonce=..., ?cb=...) to script URLs. Diffing raw URLs mints a
"new" script row and a fake change event on every plugin update. These
helpers strip only the volatile params so meaningful identifiers
(?id=GTM-XXX, ?id=AW-XXX, ?render=sitekey) survive as part of identity.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that only bust caches — never part of a script's identity.
_VOLATILE_PARAMS = frozenset({
    "ver", "version", "nonce", "cb", "cachebust", "cache", "bust",
    "rev", "build", "t", "ts", "time", "timestamp", "_", "rand", "random",
    # Google tag runtime state. gtag/GTM append their own container version and
    # per-request consent flags to the src, so the same container arrives under a
    # different URL after every publish or consent change. `gtm=4e6840` is the
    # usual culprit and is too short for the hex-value heuristic below to catch.
    # Superseded for the Google tag hosts by the `_IDENTITY_PARAMS` allowlist
    # below, which drops these and everything else Google adds later; kept
    # because the same names show up on other vendors' scripts.
    "gtm", "cx", "tag_exp", "gcs", "gcd", "dma", "dma_cps", "npa",
    "_p", "_z", "gtm_preview", "gtm_cookies_win", "gbraid", "wbraid",
    # Meta pixel runtime state. `v` is the library version (moves every Meta
    # release, same sense as `ver`) and `ex_m` is a rotating list of experiment
    # ids. The pixel id lives in the path, so neither is part of the identity.
    "v", "ex_m",
})

# Values that are clearly content hashes / cache tokens regardless of key.
_HEXLIKE_VALUE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)

# A param whose value is itself a URL carries the page the beacon fired on, not
# the beacon's identity. ActiveCampaign's prism/trackcmp trackers send the whole
# current page in `u=`/`url=`, so a 60-page site listed the same tracker sixty
# times — each as a separate high-severity "unknown script". Matched on the
# value rather than a key list because every vendor spells the key differently.
_URL_VALUE = re.compile(r"^(https?:)?//|^https?%3a%2f%2f", re.IGNORECASE)

# A bare UUID is a per-visit session or message token — `prismid=` rotates on
# every page view. Identity params (container ids, account ids, site keys) are
# vendor-shaped strings, not UUIDs. Deliberately anchored: a UUID *inside* a
# longer value is left alone.
_UUID_VALUE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _is_volatile_value(value: str) -> bool:
    """True when a param's value identifies the visit, not the script."""
    return bool(
        _HEXLIKE_VALUE.match(value) or _URL_VALUE.match(value) or _UUID_VALUE.match(value)
    )

# A content hash embedded in a filename, bounded by . or - and followed by
# another . or - — e.g. modules.75bf3488a101739acfe9.js (Hotjar),
# app-a1b2c3d4e5f60718.js, main.4f2b8c1d9e0a.chunk.js (webpack/Vite).
#
# 12 is the shortest run that is safely a hash and not content: it clears
# `bundle.min.js`, `jquery-3.6.0.min.js` and account ids like
# `hotjar-3065386.js`, which must stay part of the identity. Builds configured
# for shorter hashes (webpack's default contenthash:8) are not caught — that is
# the deliberate trade for never merging two genuinely different bundles.
_FILENAME_HASH = re.compile(r"[.-][0-9a-f]{12,}(?=[.-])", re.IGNORECASE)


def _strip_filename_hash(path: str) -> str:
    """Drop content-hash segments from the last component of a URL path."""
    if not path:
        return path
    head, _, filename = path.rpartition("/")
    cleaned = _FILENAME_HASH.sub("", filename)
    return f"{head}/{cleaned}" if head or path.startswith("/") else cleaned


# Epoch cache-busters, as seconds or milliseconds, bounded to a plausible date
# range (2001-09-09 → 2100-01-01). The bound is what makes this safe: account
# ids are the other thing that shows up as an all-digit path segment, and the
# ones long enough to reach 10 digits — Meta's 16-digit pixel id, for instance —
# land far outside any sane date. Digit count alone would merge them.
_EPOCH_RANGE = {10: (1_000_000_000, 4_102_444_800), 13: (10**12, 4_102_444_800_000)}


def _is_epoch_segment(segment: str) -> bool:
    """True when a path segment is a bare timestamp rather than an identifier."""
    bounds = _EPOCH_RANGE.get(len(segment))
    if bounds is None or not segment.isdigit():
        return False
    low, high = bounds
    return low <= int(segment) <= high


# A dotted library version occupying a whole path segment — `/0.8.69/`,
# `/3.6.0/`, `/v0.8.67-beta/`. Microsoft Clarity ships from /<version>/clarity.js
# every few days and jsDelivr-style paths do the same, so the raw path minted a
# new identity on every vendor release.
#
# At least one dot is required, which is what keeps identity out of it: account
# ids (`/46377927/`, `/i9x3wxzn9k/`) and API-version directories (`/v3/`,
# `/v2/`) have none. An API version is deliberately left in — unlike a release
# number it doesn't rotate, so a site moving from /v2/ to /v3/ is real news.
_VERSION_SEGMENT = re.compile(r"^v?\d+(\.\d+)+([.-][0-9a-z]+)*$", re.IGNORECASE)


def _strip_version_segments(path: str) -> str:
    """Drop whole path segments that are only a library version."""
    if "/" not in path:
        return path
    kept = [seg for seg in path.split("/") if not _VERSION_SEGMENT.match(seg)]
    return "/".join(kept)


def _strip_timestamp_segments(path: str) -> str:
    """Drop whole path segments that are only a cache-busting timestamp.

    HubSpot serves `/analytics/<epoch_ms>/<portal_id>.js` and rotates the
    timestamp every ~30 minutes. Left in the identity, one portal mints a new
    Script row on every visit.
    """
    if "/" not in path:
        return path
    kept = [seg for seg in path.split("/") if not _is_epoch_segment(seg)]
    return "/".join(kept)


# Hosts whose scripts are identified entirely by a container / account / site
# key. Listed as the params that ARE identity, rather than the ones that are not.
#
# The rest of this module works by denylist, which is the right shape for the
# open world of WordPress cache-busters. It is the wrong shape for a tag
# platform. Google ships new runtime params on its own schedule — `cst`, `_slc`,
# `sst`, `pscdl`, `_ip`, `sess`, `num`, `frm`, `z` have all appeared on
# `gtag/js` since this module was written — and under a denylist every unlisted
# one becomes part of the script's identity. Two symptoms, one cause: a single
# GA4 property listed as nine "files" on the Scripts tab, and an added/removed
# ScriptChange pair (so an alert pair) on every site the moment Google rotates a
# param. Chasing that with more denylist entries loses the race by design.
#
# For these hosts the identity params are a genuinely closed set, so the rule is
# inverted and a param invented next quarter can no longer split a tag.
_IDENTITY_PARAMS: tuple[tuple[str, frozenset[str]], ...] = (
    ("googletagmanager.com", frozenset({"id"})),
    ("google-analytics.com", frozenset({"id"})),
    ("googleadservices.com", frozenset({"id"})),
    ("googleads.g.doubleclick.net", frozenset({"id"})),
    # reCAPTCHA is keyed by its site key. `hl` (locale) and `badge` (placement)
    # describe how one widget renders, not which widget it is — a bilingual site
    # was listing the same reCAPTCHA once per language.
    ("google.com", frozenset({"render"})),
    # Hotjar's account id is in the path (`/c/hotjar-3065386.js`); `sv=` is the
    # recorder version and bumps on every Hotjar release.
    ("hotjar.com", frozenset()),
    # Clarity's project id is likewise in the path.
    ("clarity.ms", frozenset()),
)


def _identity_params(host: str) -> frozenset[str] | None:
    """The closed set of identity params for a tag host, or None if not one.

    Matched on the registrable suffix so `www.`, regional and shard hosts
    (`static.hotjar.com`, `script.hotjar.com`) share one rule.
    """
    bare = host.rsplit(":", 1)[0] if ":" in host else host
    for suffix, params in _IDENTITY_PARAMS:
        if bare == suffix or bare.endswith("." + suffix):
            return params
    return None


def normalize_script_url(url: str) -> str:
    """Return a stable identity URL for a script src.

    Drops volatile query params, blank-valued params and the fragment,
    lowercases scheme/host, sorts surviving params. Returns the input unchanged
    when it isn't an absolute (or protocol-relative) URL.
    """
    if not url:
        return url
    raw = "https:" + url if url.startswith("//") else url
    try:
        parts = urlsplit(raw)
    except ValueError:
        return url
    if not parts.netloc:
        return url
    identity = _identity_params(parts.netloc.lower())
    params = parse_qsl(parts.query, keep_blank_values=True)
    # A blank value identifies nothing either way — `?id=` is a misconfigured
    # tag, and keeping it would list that tag separately from every real
    # container.
    if identity is None:
        kept = [
            (k, v)
            for k, v in params
            if v and k.lower() not in _VOLATILE_PARAMS and not _is_volatile_value(v)
        ]
    else:
        # Allowlist host: everything outside the closed identity set is runtime
        # state, whether or not this module has heard of it.
        kept = [(k, v) for k, v in params if v and k.lower() in identity]
    kept.sort()
    return urlunsplit((
        parts.scheme.lower() or "https",
        parts.netloc.lower(),
        _strip_timestamp_segments(
            _strip_version_segments(_strip_filename_hash(parts.path))
        ),
        urlencode(kept),
        "",
    ))


def normalize_page_url(url: str) -> str:
    """Return a stable identity URL for a page.

    Pages are identified by scheme + host + path only: querystrings (UTM
    tags, click IDs), fragments, `www.`, and trailing slashes all vary per
    visit without changing which page it is.
    """
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.netloc:
        return url
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", host, path, "", ""))


# A conservative address check: one local part, one dot in the domain. Keeps
# "info@site.com" and rejects "not-an-email", tokens and half-typed addresses.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_recipient_email(value: str) -> str:
    """Return a stable, validated recipient address, or "" when it isn't one.

    The recipient email is form *configuration* — where a submission is sent —
    not visitor input. It is lowercased and stripped so the same address seen
    as "Info@Site.com" and "info@site.com" stores once, and garbage from a
    malformed hidden input (quotes, trailing spaces, list separators) is
    rejected rather than stored.
    """
    if not value:
        return ""
    candidate = value.strip().strip('"').strip("'").lower()
    # A "Name <addr>" style value: keep only the angle-bracketed address.
    if " <" in candidate and candidate.endswith(">"):
        candidate = candidate.split(" <", 1)[1].rstrip(">").strip()
    if not _EMAIL_RE.match(candidate):
        return ""
    return candidate
