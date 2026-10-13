"""ingest_lock lines are the evidence for (or against) batching a page load's
posts into one diff. Quiet below the thresholds, so silence means no contention.

The module logger is patched rather than read through caplog: the `apps`
logger does not propagate to the root handler caplog listens on.
"""

from unittest.mock import patch

from apps.scripts.tasks import _report_lock_contention

LOGGER = "apps.scripts.tasks.logger"


def _logged(waited, held):
    with patch(LOGGER) as log:
        _report_lock_contention("site-1", "https://a.example/", waited=waited, held=held)
    if not log.warning.called:
        return None
    fmt, *args = log.warning.call_args.args
    return fmt % tuple(args)


def test_quiet_when_lock_is_fast():
    assert _logged(waited=0.12, held=0.8) is None


def test_reports_a_long_wait():
    assert _logged(waited=0.75, held=0.1) == (
        "ingest_lock: site_id=site-1 page=https://a.example/ waited_ms=750 held_ms=100"
    )


def test_reports_a_long_hold():
    assert "held_ms=2500" in _logged(waited=0.0, held=2.5)
