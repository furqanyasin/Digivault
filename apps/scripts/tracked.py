"""Which detected scripts belong on a client's tracking inventory, and under what name.

The classifier names *every* third-party script it recognises — jQuery from a CDN,
Google Fonts, the YouTube iframe API, Cloudflare's Rocket Loader. That is the right
behaviour for the diff engine and for the injected-code heuristics, but it is the
wrong list to put in front of an agency: the question the Scripts tab answers is
"what is tracking my client's visitors", and a row for `code.jquery.com` is noise
that pushes the answer off the screen.

**Vendor allowlist.** A script is *tracked* when it is the installed tag of one
of the monitored vendors — Google, HubSpot, Hotjar, WhatConverts, ClickUp,
GoHighLevel — as decided by `monitored.tag_identity`, the same rule ingest uses
to decide what to store. Everything else is off the inventory.

The one exception is a script flagged with *high* suspicion: injected code is
nobody's vendor, and hiding it would turn a noise filter into a security hole.

**Provider families.** Google is not one entry in the classifier — it is Google
Analytics 4, Google Tag Manager, Google Ads, Google AdSense, Google Optimize,
Google Fonts, Google Maps and more, because they are genuinely different products
on different hosts. A human reading the tab wants "Google" once. Families collapse
those variants to a single name, and because the category rule runs independently,
Google Fonts and Google Maps stay out of the tracked list even though they share
the family.

Families are an explicit table rather than "the first word of the provider name":
that shortcut would merge Microsoft Clarity (session recording) with Microsoft
Bing UET (advertising), two unrelated products a reader needs to tell apart.
"""

from __future__ import annotations

from apps.scripts.models import Script
from apps.scripts.monitored import tag_identity
from apps.scripts.suspicion import SEVERITY_HIGH

_C = Script.Category

# The category allowlist this module used before the vendor allowlist. Kept
# because migration 0031 imports it; nothing live reads it.
TRACKED_CATEGORIES: frozenset[str] = frozenset({
    _C.ANALYTICS,
    _C.ADVERTISING,
    _C.TAG_MANAGEMENT,
    _C.SESSION_RECORDING,
    _C.CALL_TRACKING,
    _C.CHAT,
    _C.CRM,
    _C.PAYMENT,
})

# (provider-name prefix, family). Ordered longest-prefix-first so a specific
# product cannot be swallowed by a broader vendor prefix.
_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("Google", "Google"),
    ("HubSpot", "HubSpot"),
    ("Hotjar", "Hotjar"),
    ("WhatConverts", "WhatConverts"),
    ("ClickUp", "ClickUp"),
    ("LeadConnector", "GoHighLevel"),
    ("GoHighLevel", "GoHighLevel"),
    ("Meta Pixel", "Meta"),
    ("Facebook", "Meta"),
    ("YouTube", "YouTube"),
    ("Adobe", "Adobe"),
    ("Zendesk", "Zendesk"),
)


def provider_family(provider: str) -> str:
    """Collapse a classifier provider name to the vendor a reader recognises.

    Unrecognised providers — including "unknown" — are returned unchanged, so a
    caller can always use the result as a display label.
    """
    if not provider:
        return "unknown"
    for prefix, family in _FAMILY_PREFIXES:
        if provider == prefix or provider.startswith(prefix + " "):
            return family
    return provider


def is_tracked(src_url: str, suspicion_severity: str = "") -> bool:
    """Return True when a script belongs on the tracking inventory.

    Mirrors `tasks._should_track_script`, so the tab and the change log agree
    about which rows exist.
    """
    if suspicion_severity == SEVERITY_HIGH:
        return True
    return tag_identity(src_url) is not None
