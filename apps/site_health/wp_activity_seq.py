"""Delivery-gap detection for the WP Connect push.

The snippet's buffer table uses an autoincrement primary key, so the row id is
already a per-site monotonic sequence. Comparing the batch's lowest id against
the highest we have accepted tells us whether a flush was lost — which gives a
fire-and-forget push the delivery guarantee of a polling drain, for the cost of
one integer column rather than a second transport.

Adapted from MalCare's `enforce_auto_incr_check`: when the site's MAX(id) is
below the stored offset, the table was truncated and the server responds
`offset_reset_required` rather than silently missing events.
"""
from __future__ import annotations


def check_sequence(last_seq: int, batch_seqs: list[int]) -> int | None:
    """Return the sequence to resend from, or None when nothing is missing.

    Returns 0 for a buffer reset — "send everything you still have" — because
    after a truncate there is no meaningful offset to resume from.
    """
    if not batch_seqs:
        return None

    lowest = min(batch_seqs)

    # Buffer reset. MySQL restarts an AUTO_INCREMENT at 1 after the table is
    # dropped or truncated, so id 1 arriving from a site we have already read
    # past means the table is not the one we were counting. This must be tested
    # BEFORE the replay branch below, which would otherwise swallow it — a reset
    # batch is, by definition, entirely at or below `last_seq`.
    if lowest == 1 and last_seq > 0:
        return 0

    # Rows we have already accepted: the ack was lost, not the batch. The view
    # deduplicates on (website, sequence), so taking them again is harmless.
    if lowest <= last_seq:
        return None

    # Exactly the next row we expected.
    if lowest == last_seq + 1:
        return None

    return last_seq + 1
