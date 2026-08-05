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
    # `id` and `l` (the dataLayer name) are deliberately NOT here — those are
    # what tell two containers apart.
    "gtm", "cx", "tag_exp", "gcs", "gcd", "dma", "dma_cps", "npa",
    "_p", "_z", "gtm_preview", "gtm_cookies_win", "gbraid", "wbraid",
})

# Values that are clearly content hashes / cache tokens regardless of key.
_HEXLIKE_VALUE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)

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
    kept = [
        (k, v)
        # A blank value identifies nothing — `?id=` is a misconfigured tag, and
        # keeping it would list that tag separately from every real container.
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if v and k.lower() not in _VOLATILE_PARAMS and not _HEXLIKE_VALUE.match(v)
    ]
    kept.sort()
    return urlunsplit((
        parts.scheme.lower() or "https",
        parts.netloc.lower(),
        _strip_filename_hash(parts.path),
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
