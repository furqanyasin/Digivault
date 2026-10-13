"""Page identity for the heatmap.

A heatmap is *of a page*, so "which page is this?" has to be answered the same
way on every pageview or the data for one page splits across a dozen rows that
each look like a lonely, barely-visited page.

The snippet reports ``window.location.href`` verbatim, which is the honest
thing for it to do and the wrong thing to key on:

* ``#anchor`` fragments never reach the server on a normal request and are not
  a different page — a single blog post with three in-page anchor links became
  four rows,
* campaign parameters (``utm_*``, ``gclid``, ``fbclid``, …) are attached by the
  *referrer*, not by the page, so the same landing page arrived once per ad,
  which is precisely the page you most want a heatmap of,
* ``http://`` beside ``https://``, ``www.`` beside the bare host, and a
  trailing-slash difference are the same page to every visitor and to every CMS.

Normalisation is deliberately **server-side** rather than in the snippet. The
snippet is one cached file that clients paste into their sites, so a rule added
here works on the next pageview for every existing install; a rule added there
only reaches sites that re-paste, and a mix of old and new snippets would key
the same page two ways at once.

The parallel with ``apps/scripts/normalization.py`` is intentional, but the
shape of the rule is the opposite one: script URLs need a *denylist* because
cache-busting params are an open world, whereas a page's identity is its path,
so anything that is not a known-meaningful query param is dropped. Query
parameters that genuinely select content (``?p=12``, ``?product=x``) would be
lost by a blanket drop, so ``_MEANINGFUL_PARAMS`` keeps the handful that
real CMSes use for routing.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that route to different content rather than describing where the
# visitor came from. Everything else is dropped. Kept small on purpose: a false
# positive here re-splits a page, which is the bug this module exists to fix.
_MEANINGFUL_PARAMS = frozenset(
    {
        "p",           # WordPress plain permalinks: /?p=123
        "page_id",     # WordPress static pages
        "cat",         # WordPress category archives
        "tag",         # WordPress tag archives
        "s",           # site search results — a genuinely different page
        "q",           # site search, the other common spelling
        "product",     # WooCommerce / generic product routing
        "product_cat",
        "page",        # paginated archives: /blog/?page=3
        "paged",       # WordPress' own spelling of the same thing
        "id",          # generic id routing on hand-rolled sites
        "lang",        # localisation: /?lang=fr is a different page
        "view",
        "post_type",
    }
)

# Index documents that address the same resource as the directory itself.
_INDEX_FILES = ("index.html", "index.htm", "index.php", "default.html")

MAX_PAGE_URL_LENGTH = 2048


def normalize_page_url(raw_url: str) -> str:
    """Collapse one page's many spellings to a single stable key.

    Returns ``""`` for anything unusable, which callers treat as "drop this
    payload" — an un-keyable page cannot be aggregated into anything.
    """
    if not raw_url or not isinstance(raw_url, str):
        return ""
    raw_url = raw_url.strip()
    if not raw_url:
        return ""

    # `hostname` and `port` both parse the netloc lazily and both raise on a
    # malformed one, so they are inside the guard with `urlsplit` itself. The
    # snippet reports whatever URL the browser was on, which is untrusted.
    try:
        parts = urlsplit(raw_url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return ""

    if not host:
        return ""
    # `www.` is not a different site to a visitor and is not a different page.
    if host.startswith("www."):
        host = host[4:]

    # Scheme is normalised away for the same reason it is in script URLs: a
    # template that emits one protocol-relative link beside an https one would
    # otherwise list the same page twice and split its heat down the middle.
    # Port is kept only when it is non-default, so `:443` cannot fork a page.
    netloc = host
    if port and port not in (80, 443):
        netloc = f"{host}:{port}"

    path = parts.path or "/"
    for index_file in _INDEX_FILES:
        if path.endswith("/" + index_file):
            path = path[: -len(index_file)]
            break
    # Trailing slash is normalised *on*, matching how every CMS in this
    # codebase's client base renders its own canonical links.
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"

    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if key.lower() in _MEANINGFUL_PARAMS
    ]
    # Sorted so `?lang=fr&page=2` and `?page=2&lang=fr` are one page.
    query = urlencode(sorted(kept))

    # The fragment is dropped outright: it never reaches a server, so it cannot
    # name a different page, and in-page anchors are the single largest source
    # of duplicate page rows.
    normalized = urlunsplit(("https", netloc, path, query, ""))
    return normalized[:MAX_PAGE_URL_LENGTH]


__all__ = ["MAX_PAGE_URL_LENGTH", "normalize_page_url"]
