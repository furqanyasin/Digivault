"""Merge Script rows that share the same normalized URL.

Used by the 0009 data migration and callable in tests. Works with either the
real Script model or a migration's historical model, so it takes the model
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
