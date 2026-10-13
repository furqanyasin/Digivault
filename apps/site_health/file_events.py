"""Turning a completed file walk into timeline events.

The diff itself lives in `file_diff` as a pure function. This module owns the
database side: finding the previous complete manifest, writing `SiteEvent` rows,
and pruning the manifests nothing will compare against again.
"""
from __future__ import annotations

import logging

from apps.site_health.file_diff import diff_manifests
from apps.site_health.models import FileManifest, SiteEvent

logger = logging.getLogger(__name__)

# How many changed paths to name in one summary before saying "and N more".
_MAX_NAMED = 3


def _summary(change: dict) -> str:
    verb = {"added": "added", "removed": "removed", "modified": "modified"}[
        change["change"]
    ]
    if change["file_count"] > 1:
        return f"{change['file_count']} files {verb} under {change['path']}"
    return f"File {verb}: {change['path']}"


def record_file_changes(website, current: FileManifest) -> int:
    """Diff a completed walk against the previous one and record what changed.

    Returns the number of events written. A partial manifest is ignored: diffing
    one would report every not-yet-walked file as removed.
    """
    if not current.is_complete:
        return 0

    previous = (
        FileManifest.objects.filter(website=website, is_complete=True)
        .exclude(pk=current.pk)
        .order_by("-walked_at")
        .first()
    )
    if previous is None:
        # First complete walk — this is the baseline, not a set of changes.
        return 0

    changes = diff_manifests(previous.entries or {}, current.entries or {})

    written = 0
    for change in changes:
        severity = (
            SiteEvent.Severity.CRITICAL
            if change["sensitive"]
            else SiteEvent.Severity.WARNING
        )
        # Deduped on (walk_id, path), NOT on the summary alone. The same file
        # modified in two different walks is two findings — swallowing the
        # second is exactly how a re-infection goes unnoticed.
        event, created = SiteEvent.objects.get_or_create(
            website=website,
            event_type=SiteEvent.EventType.WP_FILE_CHANGED,
            details__walk_id=current.walk_id,
            details__path=change["path"],
            defaults={
                "summary": _summary(change),
                "category": SiteEvent.Category.FILES,
                "severity": severity,
                "source": SiteEvent.Source.PASSIVE,
                "details": {
                    "walk_id": current.walk_id,
                    "path": change["path"],
                    "change": change["change"],
                    "file_count": change["file_count"],
                },
                "object_type": "file",
                "object_id": change["path"][:200],
            },
        )
        if created:
            written += 1
            if severity == SiteEvent.Severity.CRITICAL:
                from apps.site_health.wp_alerts import dispatch_for_site_event

                dispatch_for_site_event(event)

    _prune(website, keep={current.pk, previous.pk})

    if written:
        logger.info(
            "site_health.record_file_changes: %s -> %d file event(s)",
            website.domain, written,
        )
    return written


def _prune(website, keep: set) -> None:
    """Drop manifests nothing will compare against again.

    Each one holds a path -> md5 map for the whole of wp-content. Keeping every
    historical walk grows without bound for no benefit: only the previous
    complete walk is ever read.
    """
    FileManifest.objects.filter(website=website).exclude(pk__in=keep).delete()
