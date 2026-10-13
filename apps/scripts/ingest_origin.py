"""Domain-binding for the unauthenticated ingest endpoints.

Every `/api/ingest/...` endpoint is public and identifies its site by `site_id`
alone, so the request's own origin is the only evidence that the payload came
from the site it claims. One helper rather than a copy per view: there are five
of them, they must agree, and they did not.

The fifth is the reason this paragraph names a number. Four inlined copies were
collapsed into this helper; the heatmap ingest was written later, grew its own
sixth copy of the logic, and reproduced the original bug exactly — `www.`
stripped before the scheme, 403 to every post from a site saved as
`https://www.example.com`. A new ingest endpoint calls this; it does not
reimplement it.
"""
from __future__ import annotations

from urllib.parse import urlsplit


def _host_of(value: str) -> str:
    """The bare hostname in `value`, whatever shape it arrives in.

    Accepts an Origin header, a Referer, or a stored `Website.domain` — which
    users type as `example.com`, `https://example.com` or
    `https://www.example.com/`, all of which are the same site.

    Order matters and is the whole point of this function. Stripping `www.`
    before the scheme (as the four inlined copies of this did) leaves
    `https://www.example.com` as `www.example.com`, because the string starts
    with the scheme and the `www.` prefix never matches. That compared unequal
    to the browser's `example.com` and answered 403 to every ingest, form
    submission, form error and JS error from a site whose domain happened to be
    saved with both a scheme and a `www.`.
    """
    value = (value or "").strip().lower()
    if not value:
        return ""
    if "//" not in value:
        # A bare domain, possibly with a path: give urlsplit a scheme to find.
        value = f"//{value}"
    host = urlsplit(value).netloc or ""
    # Credentials and port are not part of site identity.
    host = host.rpartition("@")[2]
    if host.startswith("["):  # IPv6 literal — the port sits after the bracket
        host = host.partition("]")[0] + "]"
    else:
        host = host.partition(":")[0]
    return host.removeprefix("www.")


def site_host(value: str) -> str:
    """The public name for `_host_of`, for matching outside the ingest views.

    The browser extension matches the page it is on against `Website.domain`
    and against credentials' `login_url`; it inherits the same three spellings
    of one site and must reduce them the same way.
    """
    return _host_of(value)


def origin_matches(request, website) -> bool:
    """Whether this request plausibly came from `website`.

    Fails open when the browser sent neither header, or when the site has no
    registered domain: the check exists to reject a payload attributed to the
    wrong site, not to require an Origin that some clients legitimately omit.
    """
    origin = request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_REFERER", "")
    origin_host = _host_of(origin)
    site_host = _host_of(website.domain)
    if not origin_host or not site_host:
        return True
    return origin_host == site_host


def page_matches(page_url: str, website) -> bool:
    """Whether the page a payload describes belongs to `website`.

    `origin_matches` fails open when the browser sent neither Origin nor
    Referer, so on its own it cannot stop a payload that names another site's
    page. The payload's `page_url` is the snippet's own `location.href`: a page
    on a different host is some other site's inventory, and diffed as this
    one's it turns up as a stream of unknown scripts "added" and then
    "removed". Same comparison, same fail-open rule for a missing value.
    """
    page_host = _host_of(page_url)
    site_host = _host_of(website.domain)
    if not page_host or not site_host:
        return True
    return page_host == site_host
