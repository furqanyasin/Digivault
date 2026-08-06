"""Merge Script and DetectedForm rows that share the same normalized identity.

Used by the 0009 / 0018 data migrations and callable in tests. Works with either
the real models or a migration's historical models, so it takes the model
classes as arguments instead of importing them.
"""

from __future__ import annotations

from collections import defaultdict

from apps.scripts.normalize import normalize_script_url

# Any explicit review verdict beats pending.
_REVIEW_PRIORITY = {"approved": 3, "blocked": 2, "ignored": 1, "pending": 0}


def merge_duplicate_scripts(script_model, script_change_model) -> int:
    """Backfill normalized_url and merge duplicate Script rows.

    Keeper = earliest created_at in each (website, normalized_url) group.
    The keeper absorbs the union of seen_on_pages, the highest-priority
    review_status, is_active if any duplicate was active, and the most
    recently seen raw src_url. ScriptChange FKs are repointed. Returns the
    number of rows deleted.
    """
    # Group first without writing: backfilling normalized_url before the
    # duplicates are deleted would trip the (website, normalized_url) unique
    # constraint when it already exists (test DBs, re-runs).
    groups: dict[tuple, list] = defaultdict(list)
    for script in script_model.objects.all().order_by("created_at"):
        normalized = normalize_script_url(script.src_url)
        groups[(script.website_id, normalized)].append(script)

    deleted = 0
    for (_, normalized), dupes in groups.items():
        if len(dupes) < 2:
            keeper = dupes[0]
            if keeper.normalized_url != normalized:
                script_model.objects.filter(pk=keeper.pk).update(normalized_url=normalized)
            continue
        keeper, rest = dupes[0], dupes[1:]

        pages = list(keeper.seen_on_pages or [])
        review = keeper.review_status
        is_active = keeper.is_active
        src_url = keeper.src_url
        last_seen = keeper.last_seen_at
        for dup in rest:
            for page in dup.seen_on_pages or []:
                if page not in pages:
                    pages.append(page)
            if _REVIEW_PRIORITY.get(dup.review_status, 0) > _REVIEW_PRIORITY.get(review, 0):
                review = dup.review_status
            is_active = is_active or dup.is_active
            if dup.last_seen_at and (last_seen is None or dup.last_seen_at > last_seen):
                last_seen = dup.last_seen_at
                src_url = dup.src_url

        script_change_model.objects.filter(script_id__in=[d.pk for d in rest]).update(
            script_id=keeper.pk
        )
        for dup in rest:
            dup.delete()
            deleted += 1
        # .update() bypasses auto_now on last_seen_at, preserving the true value.
        script_model.objects.filter(pk=keeper.pk).update(
            normalized_url=normalized,
            seen_on_pages=pages,
            review_status=review,
            is_active=is_active,
            src_url=src_url,
            last_seen_at=last_seen,
        )
    return deleted


def collapse_duplicate_changes(script_change_model, notification_model) -> int:
    """Collapse repeat unacknowledged ScriptChange rows onto one row each.

    Grouped exactly like the runtime dedupe in `process_ingest_payload`:
    (website, change_type, script) — falling back to the description when the
    change has no Script, since that is the only identity such a row carries.

    Keeper = **newest** created_at, the opposite of `merge_duplicate_scripts`.
    A Script row is an identity whose oldest row holds the true first_seen; a
    change row is one observation, and its description quotes the raw URL as it
    looked at the time. After 0017/0019 merged the Script rows underneath them,
    keeping the oldest change would leave the list quoting a URL the surviving
    Script no longer displays.

    Acknowledged rows are left alone — they record that someone acted, and the
    runtime dedupe likewise only suppresses against open changes (or ones inside
    the cooldown). Notifications on the deleted rows are repointed at the keeper
    rather than left dangling. Returns the number of rows deleted.
    """
    groups: dict[tuple, list] = defaultdict(list)
    for change in (
        script_change_model.objects.filter(acknowledged_at__isnull=True)
        .order_by("created_at")
    ):
        identity = change.script_id or ("description", change.description)
        groups[(change.website_id, change.change_type, identity)].append(change)

    deleted = 0
    for dupes in groups.values():
        if len(dupes) < 2:
            continue
        # Ordered oldest-first above, so the keeper is the last one.
        keeper, rest = dupes[-1], dupes[:-1]
        loser_pks = [d.pk for d in rest]
        notification_model.objects.filter(script_change_id__in=loser_pks).update(
            script_change_id=keeper.pk
        )
        script_change_model.objects.filter(pk__in=loser_pks).delete()
        deleted += len(loser_pks)
    return deleted


def merge_duplicate_forms(detected_form_model) -> int:
    """Recompute DetectedForm fingerprints and merge the resulting duplicates.

    Keeper = earliest first_seen_at in each (website, page_url, fingerprint)
    group. Submission counts are **summed** and the latest submit/seen
    timestamps kept: the duplicates are the same real form reached through
    different URLs, so their conversions all belong to the survivor. Returns the
    number of rows deleted.
    """
    from apps.scripts.models import DetectedForm

    groups: dict[tuple, list] = defaultdict(list)
    for form in detected_form_model.objects.all().order_by("first_seen_at"):
        fingerprint = DetectedForm.compute_fingerprint({
            "detection_type": form.detection_type,
            "form_id": form.form_id,
            "form_name": form.form_name,
            "form_action": form.form_action,
            "fields": form.fields or [],
        })
        groups[(form.website_id, form.page_url, fingerprint)].append(form)

    deleted = 0
    for (_, _, fingerprint), dupes in groups.items():
        keeper, rest = dupes[0], dupes[1:]
        submissions = sum(d.submission_count or 0 for d in dupes)
        last_submission = max(
            (d.last_submission_at for d in dupes if d.last_submission_at), default=None
        )
        last_seen = max((d.last_seen_at for d in dupes if d.last_seen_at), default=None)
        for dup in rest:
            dup.delete()
            deleted += 1
        # .update() bypasses auto_now on last_seen_at, preserving the true value.
        detected_form_model.objects.filter(pk=keeper.pk).update(
            fingerprint=fingerprint,
            submission_count=submissions,
            last_submission_at=last_submission,
            last_seen_at=last_seen,
        )
    return deleted
