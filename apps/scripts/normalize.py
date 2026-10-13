"""URL normalization — stable identity for scripts and pages.

WordPress and page builders append volatile cache-buster query params
(?ver=6.4.2, ?nonce=..., ?cb=...) to script URLs. Diffing raw URLs mints a
"new" script row and a fake change event on every plugin update. These
helpers strip only the volatile params so meaningful identifiers
(?id=GTM-XXX, ?id=AW-XXX, ?render=sitekey) survive as part of identity.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from apps.scripts.monitored import tag_identity

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
    # A JS callback name, not an identifier. HubSpot's reCAPTCHA embed spells it
    # `onload=hsRecaptchaLoaded_4e806ea2_8308_46c5_9b89_3054d907db2c` — a UUID
    # with underscores for separators and a prefix, which `_UUID_VALUE` below
    # deliberately will not match. Left in, one reCAPTCHA minted a new Script
    # row on every single page load.
    "onload",
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


# A whole path segment that is a bare UUID. Vendors that mint one per
# integration (or per visit) put it in the path, where none of the query-param
# rules above can reach it — `infird.com/cdn/986df696-a484-42dc-a3ed-0466520e31dc`
# arrived as a new identity, and therefore a new high-severity "unknown script",
# every time the value rotated.
#
# Underscores are accepted as separators alongside dashes because embed builders
# substitute them when the value has to survive as a JS identifier.
_UUID_SEGMENT = re.compile(
    r"^[0-9a-f]{8}[-_][0-9a-f]{4}[-_][0-9a-f]{4}[-_][0-9a-f]{4}[-_][0-9a-f]{12}$",
    re.IGNORECASE,
)

# An opaque build token, only ever stripped when the *previous* segment is
# literally `releases` — e.g.
# `gstatic.com/recaptcha/releases/8x-4t2pegToiW8KmThtO4AQt/recaptcha__en.js`,
# which rotates on Google's release schedule and is not a version number, a
# timestamp or a hex hash, so nothing else here catches it.
#
# The `releases/` marker is what makes this safe. A bare "long opaque segment"
# rule would also eat the account paths of vendors that legitimately key by
# them — `digitaloceanspaces.com/RMieIJj0M7RIDmr7/BLF9r_5XjpFWh0ZoYb47n/pixel.js`
# is one live example — merging unrelated third parties into a single row. A
# vendor that names a directory `releases` has told us what is in it.
_RELEASE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,}$")


def _strip_opaque_segments(path: str) -> str:
    """Drop whole path segments that identify a build or an integration token."""
    if "/" not in path:
        return path
    kept: list[str] = []
    previous = ""
    for segment in path.split("/"):
        drop = _UUID_SEGMENT.match(segment) or (
            previous.lower() == "releases" and _RELEASE_TOKEN.match(segment)
        )
        previous = segment
        if not drop:
            kept.append(segment)
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


def _canonical_vendor_path(host: str, path: str) -> tuple[str, str] | None:
    """Return a stable identity for vendor bundles with release paths.

    YouTube's widget API is served both as ``/iframe_api`` and as a release
    bundle below ``/s/player/<release>/.../www-widgetapi.js``. The release path
    is runtime packaging, not a different integration, so it must not produce
    an add/remove pair when the browser changes which loader it receives.
    """
    bare = host.rsplit(":", 1)[-1]
    filename = path.rsplit("/", 1)[-1].lower()
    if bare in {"youtube.com", "www.youtube.com"}:
        if path.rstrip("/").lower().endswith("/iframe_api"):
            return "www.youtube.com", "/iframe_api"
        if filename == "www-widgetapi.js":
            return "www.youtube.com", "/www-widgetapi.js"
    if bare == "s.ytimg.com" and filename == "www-widgetapi.js":
        return "www.youtube.com", "/www-widgetapi.js"
    return None


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
    # Meta's pixel id is in the path (`/signals/config/7847387958713764`), so
    # nothing in the querystring is identity. Under the denylist this host was
    # splitting one pixel across three rows on `r=` alone — the release channel
    # Meta serves the config from (`r=stable`, `r=c2`) plus an occasional
    # `im=1` — each of which then took turns going missing and produced a
    # fabricated "Meta Pixel URL changed" every couple of days.
    ("connect.facebook.net", frozenset()),
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
    lowercases the host, sorts surviving params. Returns the input unchanged
    when it isn't an absolute (or protocol-relative) URL.

    The scheme is always `https`, because it identifies the transport rather
    than the script: one WordPress template emitting `http://js.hs-scripts.com/
    46377927.js` while the rest of the site emits `https://` listed the same
    HubSpot portal twice and let the two halves report each other as removed.
    An `http` script on an `https` page is a mixed-content problem worth
    surfacing, but as an attribute of one script — not as a second script.
    """
    if not url:
        return url
    # A monitored vendor's tag is keyed by the account it belongs to, so every
    # file its loader pulls in collapses onto the one tag. See monitored.py.
    tag = tag_identity(url)
    if tag:
        return tag
    raw = "https:" + url if url.startswith("//") else url
    try:
        parts = urlsplit(raw)
    except ValueError:
        return url
    if not parts.netloc:
        return url
    vendor_path = _canonical_vendor_path(parts.netloc.lower(), parts.path)
    if vendor_path:
        vendor_host, vendor_path_value = vendor_path
        return urlunsplit(("https", vendor_host, vendor_path_value, "", ""))
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
        "https",
        parts.netloc.lower(),
        _strip_opaque_segments(
            _strip_timestamp_segments(
                _strip_version_segments(_strip_filename_hash(parts.path))
            )
        ),
        urlencode(kept),
        "",
    ))


def is_identity_host(url: str) -> bool:
    """True when a URL's host keys its scripts by an explicit container id.

    Callers use this to tell "the same tag under a rotated URL" apart from "a
    different tag from the same vendor". On these hosts every surviving
    identifier is deliberate, so two normalized URLs that differ at all are two
    genuinely different tags — never one tag that moved.
    """
    if not url:
        return False
    raw = "https:" + url if url.startswith("//") else url
    try:
        host = urlsplit(raw).netloc.lower()
    except ValueError:
        return False
    return _identity_params(host) is not None


# An account / container / property id: digits are what make it an id rather
# than a filename, so `fbevents` and `insight.min` are correctly passed over
# while `7847387958713764`, `i9x3wxzn9k` and `hotjar-3065386` are not.
_ID_LIKE = re.compile(r"^(?=.*\d)[A-Za-z0-9_-]{6,}$")


def identity_label(url: str) -> str:
    """Return the tag id a URL is keyed by, or "" when it has none.

    One provider name routinely covers many separate tags — a site can run four
    GA4 properties, three Google Ads conversion tags and three Meta pixels at
    once. Described by provider alone, each of their changes reads as the same
    event logged over and over; the id is the only thing that tells a reader
    which of them actually changed.
    """
    if not url:
        return ""
    normalized = normalize_script_url(url)
    raw = "https:" + normalized if normalized.startswith("//") else normalized
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    for key, value in parse_qsl(parts.query):
        if key.lower() == "id" and value:
            return value
    # Path-keyed vendors (Hotjar, a HubSpot portal, a WhatConverts account)
    # carry the id as the last segment. Only consulted for hosts whose identity
    # is a closed set, or for a monitored tag, so a random third-party filename
    # never gets mistaken for an account id.
    if _identity_params(parts.netloc.lower()) is None and tag_identity(normalized) is None:
        return ""
    segment = parts.path.rsplit("/", 1)[-1]
    segment = segment.rsplit(".", 1)[0] if "." in segment else segment
    return segment if _ID_LIKE.match(segment) else ""


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


# Schemes a form action can carry that are destinations rather than paths.
# Resolving one against the page would corrupt it into nonsense.
_NON_NAVIGATIONAL_SCHEMES = ("mailto:", "tel:", "sms:", "javascript:", "data:")


def resolve_form_action(page_url: str, action: str) -> str:
    """The absolute action a *browser* would report for `action` on `page_url`.

    `form.action` is not the action attribute. The HTML spec says the getter
    returns the document's own URL when the attribute is missing or empty, and
    resolves a relative value against it. So the snippet reports an absolute URL
    for a form whose markup says nothing at all, or says `action="/submit"`,
    while the server-side scan - which reads the attribute straight out of
    static HTML - reports "" and "/submit".

    The action is part of a form's fingerprint, so the same form observed by
    both sources hashed to two identities and stored two rows for one page. The
    Forms tab then listed one form twice, split its submissions between the
    copies, and rendered whichever sorted first - which is how a live Elementor
    contact form came to show "Action: None" and "Fields (0)" beside the seven
    fields it plainly had.

    Resolving here rather than inside the scan's extractor keeps *every* source
    on one rule, the Chrome extension and any future collector included.

    `mailto:` and friends are destinations, not paths, and pass through
    untouched - a `mailto:` action is the one case where the attribute really is
    what the form does, and it is also how such a form declares its recipient.
    """
    action = (action or "").strip()
    if action.lower().startswith(_NON_NAVIGATIONAL_SCHEMES):
        return action
    if not page_url:
        return action
    try:
        return urljoin(page_url, action)
    except ValueError:
        return action


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
