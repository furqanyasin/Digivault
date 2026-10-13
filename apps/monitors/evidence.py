"""What a blocked monitor can still know, from evidence our IP never fetches.

A host firewall that challenges our probe (SiteGround's anti-bot answers a
datacenter IP with a 202 captcha, and neither a user-agent nor solving the
puzzle clears it for long) blocks *inbound requests from us*. It cannot block:

* **the site reporting in.** The WP Connect snippet runs inside WordPress and
  POSTs out to us — an outbound request the site's own firewall never sees. Any
  accepted flush (`wp_connect_last_ack`) proves PHP booted WordPress and reached
  its database moments ago, and the snippet's 5-minute heartbeat adds a loopback
  fetch of the homepage from the site's own server (`wp_connect_loopback_*`).
* **real visitors.** The tracking snippet posts from a visitor's browser after
  the page rendered (`snippet_last_seen_at`).

Every external monitor that hits this (mySites.guru, MainWP, ManageWP) answers
with a support ticket per hosting account. This module is the alternative: when
our probe says `blocked`, these sources stand in for it, the same way Google's
second opinion does, and Google is only asked when neither has anything fresh.

Only for a probe the firewall *answered* (`blocked` straight from the checker).
A probe that timed out three times and was downgraded to `blocked` by
`liveness` stays on that path: there our own request failed, and a visit from
some minutes ago does not prove the site is up now.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

DEFAULT_SITE_WINDOW_SECONDS = 900      # three heartbeat ticks of the snippet
DEFAULT_VISITOR_WINDOW_SECONDS = 600


def _site_window() -> int:
    return getattr(settings, "EVIDENCE_SITE_WINDOW_SECONDS", DEFAULT_SITE_WINDOW_SECONDS)


def _visitor_window() -> int:
    return getattr(settings, "LIVENESS_WINDOW_SECONDS", DEFAULT_VISITOR_WINDOW_SECONDS)


def _ago(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s ago"
    return f"{seconds // 60} min ago"


def inside_view(monitor) -> dict | None:
    """A verdict for a blocked monitor from the site itself or its visitors.

    Same shape as a Google verdict — ``{"status", "status_code", "message",
    "via"}`` — or None when nothing fresh is known. Never raises: no evidence
    means the caller falls back to Google, then to `blocked`.
    """
    try:
        website = monitor.website
        if website is None:
            return None
        now = timezone.now()
        return _from_site(website, now) or _from_visitors(website, now)
    except Exception:  # noqa: BLE001
        logger.exception("inside_view failed for monitor %s", getattr(monitor, "pk", "?"))
        return None


def _from_site(website, now) -> dict | None:
    ack = website.wp_connect_last_ack
    if not ack:
        return None
    age = (now - ack).total_seconds()
    if age > _site_window():
        return None

    code = website.wp_connect_loopback_status
    loop_at = website.wp_connect_loopback_at
    loop_fresh = code is not None and loop_at is not None and (
        (now - loop_at).total_seconds() <= _site_window()
    )

    # The site fetched its own homepage and got a server error: an outage seen
    # from inside, which no firewall in front of the site can be blamed for.
    if loop_fresh and code >= 500:
        return {
            "status": "down",
            "status_code": code,
            "message": (
                f"The site's own server loaded its homepage and got HTTP {code} "
                f"({_ago((now - loop_at).total_seconds())}) — a real outage, seen "
                "from inside the site."
            ),
            "via": "site",
        }

    detail = ""
    if loop_fresh and code < 400:
        ms = website.wp_connect_loopback_ms
        detail = f" and loaded its own homepage (HTTP {code}" + (f", {ms} ms)" if ms is not None else ")")
    return {
        "status": "up",
        "status_code": code if loop_fresh and code < 400 else None,
        "message": (
            f"Up — WordPress on this site reported in {_ago(age)}{detail}. "
            "The site's firewall blocks our own checks, so the site's heartbeat "
            "stands in for them."
        ),
        "via": "site",
    }


def _from_visitors(website, now) -> dict | None:
    seen = website.snippet_last_seen_at
    if not seen:
        return None
    age = (now - seen).total_seconds()
    if age > _visitor_window():
        return None
    return {
        "status": "up",
        "status_code": None,
        "message": (
            f"Up — a real visitor's browser loaded this site {_ago(age)}. The "
            "site's firewall blocks our own checks, so real traffic stands in "
            "for them."
        ),
        "via": "visitors",
    }
