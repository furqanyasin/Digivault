"""Next-step suggestions attached to every assistant reply.

The widget only ever showed its quick questions on the welcome message, so from
the second turn on you were left with an empty input and no idea what the
assistant understood. Every reply now carries its own follow-ups, so there is
always a next step to click.

Two constraints shape the wording, and both are easy to get wrong:

1. A suggestion must not re-ask what was just answered. Offering "Any alerts?"
   underneath the alert list is the dead end this module exists to remove.
2. Every suggestion must be a phrase `detect_intent` recognises, or the chip
   answers "I'm not sure what you're asking". The parser checks for a domain
   early and greedily, so a chip like "Forms on example.com" is read as a
   *website* lookup, not a forms lookup — phrasings here are chosen against the
   real parser, and `tests/chat/test_followups.py` asserts every one of them
   still resolves.
"""
from __future__ import annotations

# Four is what fits the 380px panel without wrapping to a third row.
MAX_SUGGESTIONS = 4

# Phrasings that `detect_intent` resolves. Kept as constants because the exact
# wording is load-bearing — "Uptime monitors" reaches the monitor list while
# "Monitors up?" would fall through to the down-monitor branch.
_SUMMARY = "Dashboard summary"
_ALERTS = "Any alerts?"
_WEBSITES = "Show my websites"
_MONITORS = "Uptime monitors"
_MONITORS_DOWN = "Monitors down?"
_UNKNOWN_SCRIPTS = "Unknown scripts"
_ALL_SCRIPTS = "All scripts"
_CHANGES = "Recent changes"
_FORMS = "Detected forms"
_CLIENTS = "List my clients"
_HELP = "Help"

# Per reply type, in the order they should appear. Each list deliberately omits
# the question that produced it — see the module docstring.
_BY_TYPE: dict[str, list[str]] = {
    "help": [_SUMMARY, _ALERTS, _WEBSITES, _UNKNOWN_SCRIPTS],
    # "dashboard", "overview" and "stats" all resolve to summary too, so none of
    # them may appear here either.
    "summary": [_ALERTS, _MONITORS_DOWN, _UNKNOWN_SCRIPTS, _CHANGES],
    "scripts_list": [_UNKNOWN_SCRIPTS, _ALERTS, _FORMS, _WEBSITES],
    "unknown_scripts": [_ALL_SCRIPTS, _ALERTS, _CHANGES, _WEBSITES],
    "no_unknowns": [_ALL_SCRIPTS, _ALERTS, _CHANGES, _WEBSITES],
    "alerts_list": [_CHANGES, _MONITORS_DOWN, _UNKNOWN_SCRIPTS, _SUMMARY],
    "no_alerts": [_SUMMARY, _MONITORS_DOWN, _UNKNOWN_SCRIPTS, _WEBSITES],
    "forms_list": [_WEBSITES, _UNKNOWN_SCRIPTS, _ALERTS, _SUMMARY],
    "websites_list": [_SUMMARY, _MONITORS_DOWN, _UNKNOWN_SCRIPTS, _ALERTS],
    # Narrowing the list to the failing ones is a genuine next step, not a repeat.
    "monitors_list": [_MONITORS_DOWN, _ALERTS, _SUMMARY, _WEBSITES],
    "monitors_down": [_MONITORS, _ALERTS, _SUMMARY, _WEBSITES],
    "monitors_all_up": [_ALERTS, _SUMMARY, _UNKNOWN_SCRIPTS, _WEBSITES],
    "changes_list": [_ALERTS, _UNKNOWN_SCRIPTS, _SUMMARY, _WEBSITES],
    "clients_list": [_WEBSITES, _SUMMARY, _ALERTS],
    "client_detail": [_CLIENTS, _WEBSITES, _SUMMARY],
    "onboard_instructions": [_WEBSITES, _SUMMARY, _HELP],
    "already_onboarded": [_WEBSITES, _SUMMARY, _ALERTS],
    "empty": [_SUMMARY, _WEBSITES, _HELP],
    "error": [_HELP, _SUMMARY, _WEBSITES],
    "fallback": [_HELP, _SUMMARY, _ALERTS, _WEBSITES],
}

# Used for reply types not listed above, including any added later — a new intent
# must never leave the widget with a bare input box.
_DEFAULT = [_SUMMARY, _ALERTS, _WEBSITES, _HELP]


def _website_status(data: dict) -> list[str]:
    """A site was just described — offer the things you would look at next.

    "Scripts for <domain>" keeps the conversation on that site; the parser reads
    domain + "scripts" as a per-site lookup.
    """
    domain = (data or {}).get("domain") or ""
    chips: list[str] = []
    if domain:
        chips.append(f"Scripts for {domain}")
    # Only worth pointing at the change log when there is something in it.
    if (data or {}).get("pending_changes"):
        chips.append(_CHANGES)
    chips += [_UNKNOWN_SCRIPTS, _WEBSITES, _SUMMARY]
    return chips


def _not_found(data: dict) -> list[str]:
    """The site is not monitored — the useful next step is onboarding it."""
    query = (data or {}).get("query") or ""
    chips: list[str] = []
    if query:
        chips.append(f"onboard {query}")
    chips += [_WEBSITES, _SUMMARY]
    return chips


_CONTEXTUAL = {
    "website_status": _website_status,
    "not_found": _not_found,
}


def suggest(result: dict) -> list[str]:
    """Follow-up chips for one assistant reply, most useful first.

    Never returns an empty list for a real reply — a reply with no next step is
    the dead end this exists to remove.
    """
    result = result or {}
    reply_type = result.get("type") or ""

    builder = _CONTEXTUAL.get(reply_type)
    chips = builder(result.get("data") or {}) if builder else _BY_TYPE.get(reply_type, _DEFAULT)

    # Dedupe while preserving order — contextual builders concatenate lists that
    # can overlap.
    seen, unique = set(), []
    for chip in chips:
        if chip not in seen:
            seen.add(chip)
            unique.append(chip)
    return unique[:MAX_SUGGESTIONS]
