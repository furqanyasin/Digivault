"""Merge the Script rows four normalization gaps had split, and retire the
categories that no longer belong on the inventory.

Three things happen here, all consequences of changes landing alongside it.

**Merge.** `normalize_script_url` now treats four more things as runtime state
rather than identity: the scheme (one template emitting `http://js.hs-scripts.com/
46377927.js` beside the site's `https://` listed one HubSpot portal twice),
`connect.facebook.net`'s querystring (one Meta pixel held three rows on `r=stable`
/ `r=c2` / `im=1` alone), the `onload=` callback name (HubSpot's reCAPTCHA embed
puts a fresh UUID in it on every page load), and opaque path segments — a bare
UUID, or a build token directly below a `releases/` directory. Those fixes stop
new rows being minted; the ones already in the database have to be merged.

A separate migration from 0016/0017/0019/0023/0027 rather than an edit to them:
a database that already applied those will never re-run them and would keep its
split rows. The merge is idempotent and keyed on whatever `normalize_script_url`
returns today, which is exactly what re-running after a normalization change
needs. The keeper absorbs the union of `seen_on_pages`, the strongest review
verdict and the latest raw `src_url`, so review work already done survives.

**Collapse.** Those split rows each dedupe separately at ingest — dedupe is keyed
on the Script row — so every one of them logged its own copy of the same change.
`collapse_duplicate_changes` folds the open repeats onto one row each, matching
what the runtime dedupe will do from now on.

**Retire.** `_should_track_script` now drops scripts the classifier recognises as
infrastructure or decoration (`performance`, `social`, `security`) from the
inventory and the change log, not just from the Scripts tab's display filter.
Their existing rows are deactivated and their open changes acknowledged, because
the runtime path that would otherwise do it only reaches a website when that
website next ingests — and a client whose snippet has stopped posting would keep
a permanently unacknowledgeable "Google Static CDN removed" pinning their status.

`unknown` is deliberately left active: an unrecognised third party is the one
thing in this set worth a human's attention.

Reversing is a no-op. The merged rows are gone, re-splitting them would invent
history that never meant anything, and re-opening the acknowledged changes would
re-raise alerts about scripts the product no longer reports on.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from django.utils import timezone

    from apps.scripts.classifier import ScriptClassifier
    from apps.scripts.dedup import collapse_duplicate_changes, merge_duplicate_scripts
    from apps.scripts.tracked import TRACKED_CATEGORIES

    script_model = apps.get_model("scripts", "Script")
    change_model = apps.get_model("scripts", "ScriptChange")
    notification_model = apps.get_model("alerts", "Notification")

    merged = merge_duplicate_scripts(script_model, change_model)
    if merged:
        print(f"  merged {merged} duplicate script rows")

    collapsed = collapse_duplicate_changes(change_model, notification_model)
    if collapsed:
        print(f"  collapsed {collapsed} duplicate change rows")

    # Classified per row rather than by a category IN query: the category stored
    # on an existing row was written by whatever the classifier said at the time,
    # and several of these rows predate the entries that now name them (Bing's
    # `/p/...` endpoints, `gstatic.cn`, YouTube's widget bundle). Re-classifying
    # is what lets those be judged by today's rules.
    retire_pks = []
    for script in script_model.objects.all().only("pk", "src_url"):
        result = ScriptClassifier.classify(script.src_url)
        if result.is_known and result.category not in TRACKED_CATEGORIES:
            retire_pks.append(script.pk)

    if retire_pks:
        script_model.objects.filter(pk__in=retire_pks, is_active=True).update(
            is_active=False
        )
        acknowledged = change_model.objects.filter(
            script_id__in=retire_pks, acknowledged_at__isnull=True
        ).update(acknowledged_at=timezone.now())
        print(
            f"  retired {len(retire_pks)} untracked script rows "
            f"({acknowledged} open changes acknowledged)"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0030_recollapse_duplicate_changes"),
        ("alerts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
