"""Collapse the tracker rows that a page URL in the query string had split apart.

ActiveCampaign's prism / trackcmp beacons carry the current page in `u=`/`url=`
and a per-visit UUID in `prismid=`. Both counted as identity, so one tracker on
a 60-page site minted 60 Script rows — and 60 changes, most of them the
high-severity "Unknown script detected" that fires when nothing classifies the
host. One real dashboard reached 73 unacknowledged changes covering about six
actual scripts.

`normalize_script_url` now drops any param whose value is itself a URL or a bare
UUID, and the classifier recognises app-us1.com and leadconnectorhq.com. This
re-runs the two existing dedupe passes under those rules: merge the Script rows,
then collapse the duplicate unacknowledged changes left pointing at them.

A new migration rather than an edit to 0019/0021 — those will never re-run on a
database that already applied them, which is exactly where the split rows live.
Both helpers are idempotent and key on whatever normalization returns today.

Acknowledged changes are left alone: they record that somebody acted.

Reversing is a no-op — re-splitting merged rows would invent history.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.scripts.dedup import collapse_duplicate_changes, merge_duplicate_scripts

    merged = merge_duplicate_scripts(
        apps.get_model("scripts", "Script"),
        apps.get_model("scripts", "ScriptChange"),
    )
    if merged:
        print(f"  merged {merged} duplicate script rows")

    collapsed = collapse_duplicate_changes(
        apps.get_model("scripts", "ScriptChange"),
        apps.get_model("alerts", "Notification"),
    )
    if collapsed:
        print(f"  collapsed {collapsed} duplicate change rows")


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0022_formsubmissionerror_alerted_at_and_more"),
        # Notification rows on the deleted changes are repointed at the keeper.
        ("alerts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
