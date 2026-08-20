"""Deciding when a form's destination has really changed, and recording it.

Two writers keep `DetectedForm.recipients` current — the page ingest and the WP
Connect fetch — and each of them already compares old against new to avoid a
pointless UPDATE. This module turns that comparison into a decision about
whether a human should hear about it, which is a narrower question than "did the
bytes change".

Most differences are not news. A form Digivault has just learned about goes from
nothing to something; a plugin reorders its own notification list; a WordPress
read supersedes a guess made from the markup. Announcing any of those would post
once per form across the whole estate and train the team to ignore the channel.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.scripts.recipients import all_recipients, recipients_equal
from apps.site_health.models import SiteEvent

logger = logging.getLogger(__name__)

#: Suppress a repeat of the *same* transition for this long, matching the
#: ScriptChange cooldown. A form whose recipient flips between two addresses —
#: a staging value that gets re-applied on every deploy, say — would otherwise
#: post every night.
RECIPIENT_ALERT_COOLDOWN = timedelta(days=7)


def describe_recipient_change(old: dict, new: dict) -> dict | None:
    """What changed between two recipient sets, or `None` if it isn't news.

    Silent by design in two cases: an unchanged set (including one merely
    reordered — `recipients_equal` ignores order within a kind), and a first
    discovery, where the form had no known destination at all.
    """
    if recipients_equal(old, new):
        return None

    old_all = all_recipients(old)
    if not old_all:
        return None

    new_all = all_recipients(new)
    old_bcc = set((old or {}).get("bcc") or [])
    new_bcc = set((new or {}).get("bcc") or [])

    added = [e for e in new_all if e not in old_all]
    removed = [e for e in old_all if e not in new_all]
    # An address still receiving mail, but no longer as a visible destination.
    # Neither added nor removed, and easy to miss if not called out.
    moved_to_bcc = [e for e in new_bcc if e in old_all and e not in old_bcc]

    if not new_all:
        return {
            "severity": SiteEvent.Severity.CRITICAL,
            "summary_verb": "no longer delivers to anyone",
            "added": [], "removed": removed, "moved_to_bcc": [],
        }

    # Anything gained, lost from To, or hidden into Bcc is worth a warning.
    # Only losing a Cc is housekeeping.
    old_to = set((old or {}).get("to") or [])
    new_to = set((new or {}).get("to") or [])
    material = bool(added) or bool(moved_to_bcc) or bool(old_to - new_to)
    return {
        "severity": SiteEvent.Severity.WARNING if material else SiteEvent.Severity.INFO,
        "summary_verb": "changed where it delivers",
        "added": added, "removed": removed, "moved_to_bcc": moved_to_bcc,
    }


def form_label(form) -> str:
    """A name a human can find in the Forms tab."""
    return form.form_name or form.form_id or form.provider or "Unnamed form"


def _summary(form, change: dict) -> str:
    site = form.website.name or form.website.domain
    return f"{site} — form “{form_label(form)}” {change['summary_verb']}"[:500]


def record_recipient_change(
    form, *, old_recipients: dict, old_source: str, new_source: str
) -> SiteEvent | None:
    """Record that this form's destination changed, and queue the announcement.

    Call **after** `form.recipients` is saved. Returns the `SiteEvent`, or `None`
    when there is nothing to announce.

    A change only counts **within one source**. `page` → `wordpress` reporting
    different addresses is a better read of the same form, not an edit to it —
    the markup never had the real address to begin with. Treating it as a change
    would fire for every form on the estate the first time WP Connect answers.
    """
    if not old_source or old_source != new_source:
        return None

    change = describe_recipient_change(old_recipients, form.recipients)
    if change is None:
        return None

    summary = _summary(form, change)
    since = timezone.now() - RECIPIENT_ALERT_COOLDOWN
    # Keyed on the actual old/new values, not the summary text: two different
    # transitions on the same form ("changed where it delivers") would
    # otherwise share one generic summary and dedupe against each other. The
    # cooldown is meant to suppress a repeat of the *same* transition only.
    if SiteEvent.objects.filter(
        website_id=form.website_id,
        event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED,
        details__form_id=str(form.pk),
        details__old=old_recipients,
        details__new=form.recipients,
        occurred_at__gte=since,
    ).exists():
        return None

    event = SiteEvent.objects.create(
        website=form.website,
        event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED,
        severity=change["severity"],
        summary=summary,
        details={
            "form_id": str(form.pk),
            "form_label": form_label(form),
            "page_url": form.page_url,
            "source": new_source,
            "old": old_recipients,
            "new": form.recipients,
            "added": change["added"],
            "removed": change["removed"],
            "moved_to_bcc": change["moved_to_bcc"],
        },
    )

    # Posted after the surrounding transaction commits, never inside it. The
    # page-ingest writer runs inside `process_ingest_payload`'s transaction, and
    # a ClickUp call there would hold it open for the client's 10s timeout; the
    # form-error alert is split off for the same reason. on_commit also means a
    # rolled-back ingest announces nothing.
    def _queue():
        from apps.scripts.tasks import deliver_recipient_change_alert

        deliver_recipient_change_alert.delay(str(event.pk))

    transaction.on_commit(_queue)
    return event
