"""When is a script's absence evidence that it was removed?

Pure logic, no database access — `tasks.process_ingest_payload` owns the I/O.

A page load is one observation, and a tag being missing from it says very
little on its own. Consent banners hold GA4, Clarity and the ad pixels back
until the visitor accepts; ad blockers stop them outright; AdSense and the Google
Ads remarketing tags load on some visits and not others. Every one of those is a
tag that is still installed and simply did not run for *this* visitor.

The rule this replaced called a tag removed once it was missing from three
consecutive observation buckets of one page. On a quiet page three buckets are
three visitors, and three visitors in a row declining cookies is an ordinary
afternoon — so the tag was reported removed, then "added" again by the next
visitor who accepted, and the cycle repeated for as long as the site had
traffic. That was the whole of the repeating add/remove pairs in the change log.

The rule here asks the question statistically. From this page's own history we
know how often the tag shows up when it is installed (`p`). A tag present on
every load going missing three times is news; a tag that loads for 40% of
visitors going missing three times is Tuesday. The number of consecutive misses
required is the smallest `n` with `(1 - p) ** n` below `FALSE_REMOVAL_ODDS` —
the chance that an installed tag would miss that many loads by bad luck.
"""
from __future__ import annotations

import math

# Accepted chance that an installed tag is reported removed by bad luck alone.
FALSE_REMOVAL_ODDS = 0.01

# Never fewer than this many consecutive misses, however steady the tag was.
MIN_ABSENT_LOADS = 3

# A tag whose presence rate needs more misses than this to judge is too
# intermittent for a removal to mean anything (a rotating ad creative, a tag
# fired by one campaign). It is never *reported* removed; the weekly sweep
# retires it silently once nobody has seen it anywhere for a month.
MAX_ABSENT_LOADS = 40

# Loads of history, counted from the tag's last sighting backwards, needed
# before its presence rate is trusted. A tag seen on one load has a measured
# rate of 100% and would otherwise be "removed" after three quiet visits.
MIN_HISTORY_LOADS = 3


def required_absences(presence_rate: float) -> int:
    """Consecutive misses before a tag present at `presence_rate` counts as gone."""
    if presence_rate >= 1.0:
        return MIN_ABSENT_LOADS
    if presence_rate <= 0.0:
        return MAX_ABSENT_LOADS + 1
    needed = math.ceil(math.log(FALSE_REMOVAL_ODDS) / math.log(1.0 - presence_rate))
    return max(MIN_ABSENT_LOADS, needed)


def confirmed_absences(loads: list[set[str]]) -> dict[str, int]:
    """Identities these loads are confident have left the page.

    `loads` are *completed* page loads, newest first, each the set of script
    identities seen across all of that load's posts. Returns identity -> the
    length of its current absent run, for every identity whose run is long
    enough given how often it appeared before the run began.

    The load still in progress must not be passed in: its early posts predate
    what GTM injects, which is the partial-capture problem all over again.
    """
    everything: set[str] = set().union(*loads) if loads else set()
    confirmed: dict[str, int] = {}
    for ident in everything:
        run = 0
        for load in loads:
            if ident in load:
                break
            run += 1
        if run == 0:
            continue
        history = loads[run:]
        if len(history) < MIN_HISTORY_LOADS:
            continue
        rate = sum(1 for load in history if ident in load) / len(history)
        needed = required_absences(rate)
        if needed <= MAX_ABSENT_LOADS and run >= needed:
            confirmed[ident] = run
    return confirmed
