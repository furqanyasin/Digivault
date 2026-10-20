"""Second opinion on a failed probe, from the people actually using the site.

Stacks Monitor probes from one public IP. That IP can be challenged, rate-limited or
blackholed by any WAF on any of the client sites it watches, and when it is, the
monitor reports an outage for a site that is serving visitors perfectly well.
Buying probe capacity in a second region is the usual cure; this is the cure
available without buying anything.

The platform already records `website.last_seen_at` on every ingest, and ingest
arrives from a real browser that has just loaded the client's page. It costs no
outbound requests, it comes from thousands of residential IPs rather than ours,
and no WAF can suppress it. If our probe cannot reach a site that was serving
someone ninety seconds ago, the honest conclusion is that we are blocked — not
that the site is down.

Three properties keep this from becoming a way to hide real outages:

* It can only ever **suppress** an alert. There is no path here that marks a
  monitor up, so it cannot invent uptime it did not observe.
* The window is short. Ten minutes of no visitors and corroboration stops, so a
  genuine outage on a quiet site is reported one window late at worst.
* It is capped. After `LIVENESS_MAX_SUPPRESSED_CHECKS` suppressions in a row the
  alert fires anyway. A permanently blocked monitor must not go permanently
  silent — at that point the blocking itself is the thing worth waking up for.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_SECONDS = 600
DEFAULT_MAX_SUPPRESSED_CHECKS = 6


def _window_seconds() -> int:
    return getattr(settings, "LIVENESS_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS)


def _max_suppressed() -> int:
    return getattr(
        settings, "LIVENESS_MAX_SUPPRESSED_CHECKS", DEFAULT_MAX_SUPPRESSED_CHECKS
    )


def corroborate_liveness(monitor) -> tuple[bool, str]:
    """Is this site demonstrably serving real people despite a failed probe?

    Returns ``(suppress, reason)``. ``suppress`` True means the caller should
    record the check as ``blocked`` and skip the down alert.

    Any failure in here returns False. Failing toward alerting is the safe
    direction: a spurious page is recoverable, a missed outage is not.
    """
    try:
        website = monitor.website
        if website is None or not website.snippet_last_seen_at:
            return False, ""

        if monitor.consecutive_blocks >= _max_suppressed():
            logger.warning(
                "monitor %s: %d consecutive suppressions — alerting despite recent "
                "visitor traffic, because being unable to see a site this long is "
                "itself the problem",
                monitor.pk, monitor.consecutive_blocks,
            )
            return False, ""

        window = _window_seconds()
        age = (timezone.now() - website.snippet_last_seen_at).total_seconds()
        if age > window:
            return False, ""

        return True, (
            f"A real visitor's browser loaded this site {int(age)}s ago, so it is "
            "serving traffic — our monitor is being blocked, not the site being "
            "down. Allowlist the monitor to restore coverage."
        )
    except Exception:
        logger.exception("corroborate_liveness failed for monitor %s", getattr(monitor, "pk", "?"))
        return False, ""
