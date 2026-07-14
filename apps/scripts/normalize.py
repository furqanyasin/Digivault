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
})

# Values that are clearly content hashes / cache tokens regardless of key.
_HEXLIKE_VALUE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)


def normalize_script_url(url: str) -> str:
    """Return a stable identity URL for a script src.

    Drops volatile query params and the fragment, lowercases scheme/host,
    sorts surviving params. Returns the input unchanged when it isn't an
    absolute (or protocol-relative) URL.
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
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _VOLATILE_PARAMS and not _HEXLIKE_VALUE.match(v)
    ]
    kept.sort()
    return urlunsplit((
        parts.scheme.lower() or "https",
        parts.netloc.lower(),
        parts.path,
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
