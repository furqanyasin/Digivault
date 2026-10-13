"""The only vendors Digivault watches, and what one tag of each looks like.

Six vendors: **Google, HubSpot, Hotjar, WhatConverts, ClickUp, GoHighLevel.**
Everything else — Meta Pixel, Microsoft Clarity, TikTok, consent banners,
CDNs, unrecognised third parties — is not stored and never alerted on. The one
exception lives in `tasks._should_track_script`: a URL with high-confidence
signs of injected code (see `suspicion.analyse`) is kept whoever serves it,
because that is a hack, not a vendor.

**One tag, one identity.** A tag installed in the site's header runs on every
page and pulls in a trail of sub-resources: HubSpot's loader fetches its
analytics, cookie-banner and ads-pixel files; Hotjar's fetches a recorder
bundle; the GoHighLevel loader fetches the chat widget; GTM re-requests each
Google tag through `gtag/destination`. Each of those used to be its own Script
row with its own "added" and "removed" alerts, so one HubSpot install read as
six scripts and a vendor shipping a new bundle read as a change to the site.

`tag_identity` answers with the tag the site *installed*, keyed by the account
id where the URL carries one:

    Google        gtm.js?id=GTM-…, gtag/js?id=G-/AW-/DC-/GT-/GF-… (gtag/destination
                  is the same tag), adsbygoogle.js?client=ca-pub-…, conversion_async.js
    HubSpot       one per portal: any HubSpot URL carrying the portal id maps to
                  js.hs-scripts.com/<portal>.js; plus the forms and meetings embeds
    Hotjar        static.hotjar.com/c/hotjar-<site id>.js
    WhatConverts  <host>/<account id>.js, or the file when the URL carries no id
    ClickUp       the forms embed on app-cdn.clickup.com
    GoHighLevel   the widget loader on leadconnectorhq.com, and each msgsndr.com
                  embed (form_embed.js, external tracking)

Anything else from these vendors (show_ads_impl, script.hotjar.com modules,
hsadspixel's pixels.js, Google Fonts, reCAPTCHA, Maps) answers None: it is a
dependency the vendor manages, and it coming and going is not the site
changing. `tag_identity(tag_identity(x)) == tag_identity(x)` for every x —
normalize_script_url relies on that.

Pure functions, no DB access.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit

VENDORS: tuple[str, ...] = (
    "Google", "HubSpot", "Hotjar", "WhatConverts", "ClickUp", "GoHighLevel",
)

# A Google tag id: GTM- (container), G- (GA4), AW- (Ads), DC- (Floodlight),
# GT- (Google tag), GF- (call forwarding), UA- (legacy).
_GOOGLE_ID = re.compile(r"^(?:GTM|G|AW|DC|GT|GF|UA)-[A-Z0-9]+$", re.I)
_ADSENSE_CLIENT = re.compile(r"^ca-pub-\d+$", re.I)

_HUBSPOT_HOSTS = (
    "hs-scripts.com", "hs-analytics.net", "hs-banner.com", "hsforms.net",
    "hsforms.com", "hsadspixel.net", "hscollectedforms.net", "hubspot.com",
    "hubapi.com", "hsappstatic.net", "usemessages.com", "hs-sites.com",
)
# Where each HubSpot host puts the portal id, when it carries one.
_HUBSPOT_PORTAL = (
    ("hs-scripts.com", re.compile(r"^/(\d{4,})\.js$")),
    ("hs-analytics.net", re.compile(r"^/analytics/\d+/(\d{4,})\.js$")),
    ("hs-banner.com", re.compile(r"^/(?:v2/)?(\d{4,})/banner\.js$")),
    ("hsforms.net", re.compile(r"^/forms/embed/(\d{4,})\.js$")),
)
_HUBSPOT_FORMS_LIB = re.compile(r"^/forms/(?:embed/)?v2\.js$")
_HUBSPOT_MEETINGS = re.compile(r"/meetingsembed/", re.I)

_HOTJAR_TAG = re.compile(r"^/c/(hotjar-\d+)\.js$")

_WHATCONVERTS_HOSTS = ("whatconverts.com", "ksrndkehqnwntyxlhgto.com")
_WHATCONVERTS_ACCOUNT = re.compile(r"/(\d{3,})\.js$")

_MSGSNDR_EMBED = re.compile(r"^/js/([a-z0-9_-]+)\.js$")


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _on_any(host: str, domains) -> bool:
    return any(_on(host, d) for d in domains)


def _query_value(query: str, key: str) -> str:
    for k, v in parse_qsl(query, keep_blank_values=True):
        if k.lower() == key:
            return v.strip()
    return ""


def _google(host: str, path: str, query: str) -> str | None:
    lower = path.lower()
    if _on(host, "googletagmanager.com") or _on(host, "google-analytics.com"):
        tag_id = _query_value(query, "id")
        if not _GOOGLE_ID.match(tag_id):
            return None
        if lower == "/gtm.js":
            return f"https://www.googletagmanager.com/gtm.js?{urlencode({'id': tag_id})}"
        if lower in ("/gtag/js", "/gtag/destination"):
            return f"https://www.googletagmanager.com/gtag/js?{urlencode({'id': tag_id})}"
        return None
    if _on(host, "googlesyndication.com") and lower == "/pagead/js/adsbygoogle.js":
        client = _query_value(query, "client")
        if not _ADSENSE_CLIENT.match(client):
            return None
        return (
            "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?"
            + urlencode({"client": client})
        )
    if _on(host, "googleadservices.com") and lower in (
        "/pagead/conversion.js", "/pagead/conversion_async.js",
    ):
        return "https://www.googleadservices.com/pagead/conversion_async.js"
    return None


def _hubspot(host: str, path: str) -> str | None:
    for domain, pattern in _HUBSPOT_PORTAL:
        if _on(host, domain):
            m = pattern.match(path)
            if m:
                return f"https://js.hs-scripts.com/{m.group(1)}.js"
    if _on(host, "hsforms.net") and _HUBSPOT_FORMS_LIB.match(path):
        return "https://js.hsforms.net/forms/embed/v2.js"
    if _on(host, "hsappstatic.net") and _HUBSPOT_MEETINGS.search(path):
        return "https://static.hsappstatic.net/MeetingsEmbed/ex/MeetingsEmbedCode.js"
    return None


def tag_identity(src: str) -> str | None:
    """The monitored tag `src` is, as a canonical URL — or None if it is not one."""
    if not src:
        return None
    raw = "https:" + src if src.startswith("//") else src
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    host = parts.netloc.lower().rpartition("@")[2].partition(":")[0]
    path = parts.path or "/"

    google = _google(host, path, parts.query)
    if google:
        return google
    if _on_any(host, _HUBSPOT_HOSTS):
        return _hubspot(host, path)
    if _on(host, "hotjar.com"):
        m = _HOTJAR_TAG.match(path)
        return f"https://static.hotjar.com/c/{m.group(1)}.js" if m else None
    if _on_any(host, _WHATCONVERTS_HOSTS):
        # Keyed by account where the URL carries one; the older installs
        # (`/js/tracking.js`) carry it inline, so the file is the identity.
        m = _WHATCONVERTS_ACCOUNT.search(path)
        return f"https://{host}/{m.group(1)}.js" if m else f"https://{host}{path.lower()}"
    if _on(host, "clickup.com"):
        return "https://app-cdn.clickup.com/forms-embed.js" if _on(host, "app-cdn.clickup.com") else None
    if _on(host, "leadconnectorhq.com"):
        # loader.js fetches chat-widget/loader.js and its helpers: one install.
        return "https://widgets.leadconnectorhq.com/loader.js" if host.startswith("widgets.") else None
    if _on(host, "msgsndr.com"):
        m = _MSGSNDR_EMBED.match(path.lower())
        return f"https://link.msgsndr.com/js/{m.group(1)}.js" if m else None
    return None
