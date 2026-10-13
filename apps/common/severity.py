"""One ordering for every severity word the platform uses.

Severity was defined three times and the definitions disagreed.
`ScriptChange.Severity` has offered `critical` since it was written;
`AlertRule.min_severity` never listed it, and `AlertService`'s private rank map
never mapped it. The matcher read the rank with `.get(severity, 0)`, so a
`critical` change scored below the lowest possible rule minimum and matched no
rule at all — the one severity the product exists to surface was the one it
could not deliver.

Two vocabularies reach this module and both are kept, because they name the
same axis for different objects: script changes are graded
critical/high/medium/low, while `SiteEvent` is graded critical/warning/info.
They share ranks so a rule can gate both without a translation table.

**Unknown words never rank 0.** That default is what turned a missing entry
into silence. An unrecognised *observed* severity ranks at the top and an
unrecognised *rule minimum* ranks at the bottom, so the failure mode of a word
nobody has mapped yet is an alert too many rather than an alert nobody gets.
"""

from __future__ import annotations

# Ascending urgency. The two vocabularies are interleaved deliberately: an
# "info" SiteEvent and a "low" ScriptChange are the same amount of urgent.
_RANKS: dict[str, int] = {
    "info": 1,
    "low": 1,
    "warning": 2,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

#: Rule minimums, ascending. The label is what the dashboard shows.
MIN_SEVERITY_CHOICES: list[tuple[str, str]] = [
    ("critical", "Critical only"),
    ("high", "High & above"),
    ("medium", "Medium & above"),
    ("low", "All"),
]

MAX_RANK = max(_RANKS.values())
MIN_RANK = min(_RANKS.values())


def rank(severity: str | None, *, default: int) -> int:
    """Rank `severity`, falling back to `default` when the word is unmapped.

    `default` is mandatory and has no sensible universal value — which way an
    unknown word should fall depends entirely on which side of the comparison
    it is on. Callers should prefer `meets()`, which picks both for them.
    """
    return _RANKS.get((severity or "").strip().lower(), default)


def meets(observed: str | None, minimum: str | None) -> bool:
    """Whether an observed severity clears a rule's minimum.

    An unmapped `observed` clears every minimum and an unmapped `minimum` is
    cleared by everything, so a severity word that has been added to a model
    but not yet to this table is over-delivered rather than dropped.
    """
    return rank(observed, default=MAX_RANK) >= rank(minimum, default=MIN_RANK)
