"""Which detected scripts belong on a client's tracking inventory, and under what name.

The classifier names *every* third-party script it recognises — jQuery from a CDN,
Google Fonts, the YouTube iframe API, Cloudflare's Rocket Loader. That is the right
behaviour for the diff engine and for the injected-code heuristics, but it is the
wrong list to put in front of an agency: the question the Scripts tab answers is
"what is tracking my client's visitors", and a row for `code.jquery.com` is noise
that pushes the answer off the screen.

Two rules do the work:

**Category allowlist.** A script is *tracked* when its category is one an agency
is accountable for — analytics, advertising, tag management, session recording,
call tracking, chat, CRM, payment. `performance` (libraries, CDNs, fonts, maps,
video players), `social` (share buttons, review widgets, embeds), `security`
(reCAPTCHA, consent banners) and `unknown` are not. This is a category rule, not a
provider list, so a new marketing tag added to the classifier is tracked the day
it lands — nothing here has to be edited to keep up.

The one exception is a script flagged `is_suspicious`: an injected payload is
never in a tracked category (injections classify as `unknown` by definition), and
hiding it would turn a noise filter into a security hole.

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

_C = Script.Category

# Categories that belong on the tracking inventory. Everything else is
# infrastructure or decoration and is filtered out of the Scripts tab.
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


def is_tracked(category: str, is_suspicious: bool = False) -> bool:
    """Return True when a script belongs on the tracking inventory.

    `is_suspicious` overrides the category rule: injected code classifies as
    `unknown`, and a noise filter must not be the thing that hides it.
    """
    if is_suspicious:
        return True
    return category in TRACKED_CATEGORIES
