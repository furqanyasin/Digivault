"""The `{to, cc, bcc}` shape a detected form's destinations are stored in.

Pure functions, no DB access, so the ingest task, the server-side scan and the
WP Connect fetch can all write the same shape without duplicating the parsing.

Kept out of `normalize.py`, which is about URL and script *identity*. A recipient
list is a different concern with different rules, and `normalize_recipient_email`
there deliberately rejects a comma-joined value — one address or nothing. That is
the right answer for one field and the wrong one for a list, which is why
`normalize_recipient_list` splits first and normalizes each part.
"""
from __future__ import annotations

from apps.scripts.normalize import normalize_recipient_email

#: A form with more than this many addresses in one kind is misconfigured or
#: hostile; the cap keeps one bad plugin value out of every row and payload.
MAX_RECIPIENTS_PER_KIND = 20

_KINDS = ("to", "cc", "bcc")

#: The shape of a form with no known destination. A fresh dict every read —
#: a module-level constant would be mutated by callers through its lists.
EMPTY_RECIPIENTS: dict = {"to": [], "cc": [], "bcc": []}


def normalize_recipient_list(value) -> list[str]:
    """Every valid address in `value`, normalized, deduped, in order.

    Accepts what each source actually produces: a delimited string from page
    markup and the server-side scan, a JSON array from the WP Connect route.
    Junk entries are dropped rather than rejecting the whole list — one
    unparseable address in an Elementor "To" must not lose the others.
    """
    if not value:
        return []

    parts: list[str] = []
    if isinstance(value, (list, tuple)):
        for item in value:
            parts.extend(str(item).replace(";", ",").split(","))
    else:
        parts.extend(str(value).replace(";", ",").split(","))

    out: list[str] = []
    for part in parts:
        email = normalize_recipient_email(part)
        if email and email not in out:
            out.append(email)
        if len(out) >= MAX_RECIPIENTS_PER_KIND:
            break
    return out


def build_recipients(to=None, cc=None, bcc=None) -> dict:
    """The canonical dict, with all three keys always present.

    An address is listed once, under the strongest kind it appears in: a To is
    also a Cc on plenty of real forms, and showing it twice reads as two
    destinations rather than one.
    """
    to_list = normalize_recipient_list(to)
    cc_list = [e for e in normalize_recipient_list(cc) if e not in to_list]
    seen = set(to_list) | set(cc_list)
    bcc_list = [e for e in normalize_recipient_list(bcc) if e not in seen]
    return {"to": to_list, "cc": cc_list, "bcc": bcc_list}


def _kind(recipients, kind: str) -> list[str]:
    """One kind out of a possibly-partial dict.

    Rows predating this shape, and anything hand-edited, can be missing keys or
    not be a dict at all; every reader goes through here so none of them has to
    care.
    """
    if not isinstance(recipients, dict):
        return []
    value = recipients.get(kind)
    return [str(e) for e in value] if isinstance(value, (list, tuple)) else []


def recipients_equal(a, b) -> bool:
    """Whether two recipient dicts mean the same thing.

    Order-insensitive within a kind: plugins reorder their own notification
    lists, and re-announcing that as a change would cry wolf. Kind-sensitive
    across them: an address moved from To to Bcc has stopped being a visible
    destination, which is exactly the sort of edit the team wants to hear about.
    """
    return all(set(_kind(a, k)) == set(_kind(b, k)) for k in _KINDS)


def all_recipients(recipients) -> list[str]:
    """Every address, To then Cc then Bcc."""
    out: list[str] = []
    for kind in _KINDS:
        for email in _kind(recipients, kind):
            if email not in out:
                out.append(email)
    return out


def primary_recipient(recipients) -> str:
    """The one address to show when there is only room for one.

    Falls back to a Cc, because a Cc-only form does have a destination and
    reporting "" for it would read as "nobody receives this".
    """
    for kind in _KINDS:
        values = _kind(recipients, kind)
        if values:
            return values[0]
    return ""
