"""Reconciling passive component detection with attributed WP Connect events.

The obvious rule — suppress `wp_assets` inference whenever WP Connect is live —
is wrong. `upgrader_process_complete` does not fire for a plugin swapped in over
SFTP, installed by WP-CLI, or written by an attacker, so passive detection
catches changes hooks structurally cannot.

So both run and merge. When an attributed event arrives matching a passive row
on (kind, slug, version) inside the window, the passive row is upgraded in place
rather than duplicated: the timeline self-corrects within minutes and never
shows one plugin update twice.

What is left over is the interesting part. A passive component change still
unmatched after the window means the site changed with no corresponding admin
action — an SFTP edit, a WP-CLI run, or a compromise. That is a signal, not
dedupe residue, and it exists only because Digivault has both detection paths.
MalCare, having only the hook path, cannot produce it.
"""
from __future__ import annotations

import logging

from django.db.models import Q
from django.utils import timezone
from django.utils.timezone import timedelta

from apps.site_health.models import SiteEvent

logger = logging.getLogger(__name__)

# How long a passive row stays eligible to be claimed by its attributed twin.
# Generous on purpose: passive detection fires when the front-end asset version
# changes, which can lag the admin action by a full cache cycle.
MERGE_WINDOW_HOURS = 24

_UNATTRIBUTED_MARK = " — changed outside wp-admin"

# The categories where "no admin action" is meaningful. A content or commerce
# event has no passive counterpart at all, so it can never be unattributed.
_COMPONENT_CATEGORIES = (
    SiteEvent.Category.PLUGINS,
    SiteEvent.Category.THEMES,
    SiteEvent.Category.CORE,
)


def component_key(details: dict) -> tuple[str, str, str] | None:
    """Return (kind, slug, version) for a component event, or None.

    Case-folded because the two producers disagree: `wp_assets` lowercases slugs
    out of URLs while WordPress hooks report whatever the plugin header says.
    A case mismatch must not be the reason a merge silently fails.
    """
    if not isinstance(details, dict):
        return None
    slug = str(details.get("slug") or "").strip().lower()
    if not slug:
        return None
    kind = str(details.get("kind") or "").strip().lower()
    version = str(
        details.get("new_version") or details.get("version") or ""
    ).strip().lower()
    return kind, slug, version


def merge_into_passive(
    website,
    details: dict,
    actor: str = "",
    actor_wp_id: int | None = None,
    actor_ip: str | None = None,
    sequence: int | None = None,
) -> bool:
    """Claim a matching passive row for this attributed event.

    Returns True when a row was upgraded, in which case the caller must NOT
    create its own event — the upgraded row IS the event.
    """
    key = component_key(details)
    if key is None:
        return False

    cutoff = timezone.now() - timedelta(hours=MERGE_WINDOW_HOURS)
    candidates = SiteEvent.objects.filter(
        website=website,
        source=SiteEvent.Source.PASSIVE,
        category__in=_COMPONENT_CATEGORIES,
        occurred_at__gte=cutoff,
    ).order_by("-occurred_at")

    for row in candidates:
        row_key = component_key(row.details)
        if row_key is None or row_key[:2] != key[:2]:
            continue
        # Hook events often omit a version. The passive asset event still
        # represents the same component change, so an empty hook version is a
        # wildcard; a supplied version must continue to match exactly.
        if key[2] and row_key[2] != key[2]:
            continue
        row.source = SiteEvent.Source.WP_CONNECT
        row.actor = actor
        row.actor_wp_id = actor_wp_id
        row.actor_ip = actor_ip
        row.sequence = sequence
        row.summary = row.summary.replace(_UNATTRIBUTED_MARK, "")
        row.save(
            update_fields=[
                "source", "actor", "actor_wp_id", "actor_ip", "sequence", "summary",
            ]
        )
        return True

    return False


def flag_unattributed_component_changes() -> int:
    """Mark passive component changes that no admin action ever explained.

    Only for sites where WP Connect is reporting. Everywhere else every change
    is unattributed by construction, and flagging them all would be pure noise
    rather than a signal.
    """
    cutoff = timezone.now() - timedelta(hours=MERGE_WINDOW_HOURS)
    stale = SiteEvent.objects.filter(
        source=SiteEvent.Source.PASSIVE,
        category__in=_COMPONENT_CATEGORIES,
        occurred_at__lt=cutoff,
        website__wp_connect_last_ack__isnull=False,
    ).exclude(Q(summary__endswith=_UNATTRIBUTED_MARK))

    flagged = 0
    for row in stale:
        row.severity = SiteEvent.Severity.WARNING
        row.summary = (row.summary + _UNATTRIBUTED_MARK)[:500]
        row.save(update_fields=["severity", "summary"])
        # A component that changed with no admin action is the one finding here
        # worth interrupting someone for, so it alerts at flag time.
        from apps.site_health.wp_alerts import dispatch_for_site_event

        dispatch_for_site_event(row)
        flagged += 1

    if flagged:
        logger.info(
            "site_health.flag_unattributed_component_changes: flagged %d", flagged
        )
    return flagged
