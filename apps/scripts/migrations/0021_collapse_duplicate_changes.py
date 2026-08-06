"""Collapse the repeat change alerts that pre-normalization ingest left behind.

Until 0017 taught `normalize_script_url` about epoch path segments and 0019
taught it about dotted version segments, a HubSpot analytics tag
(`/analytics/<epoch_ms>/<portal>.js`, rotated every ~30 minutes) and a Clarity
recorder (`/<version>/clarity.js`, released every few days) minted a new Script
row on every rotation. The site-wide dedupe in `process_ingest_payload` keys on
the Script row, so a new row meant a new high-severity "Unknown script detected"
change — the same tag reported over and over, day after day.

0017 and 0019 merged the Script rows and repointed the changes onto one keeper,
which is what left the dashboard listing one script eight times with eight
different raw URLs quoted in the descriptions. Those Script rows are fixed; the
change rows they minted were never cleaned up, and being unacknowledged they sit
at the top of the list and hold the site's status down.

Only unacknowledged rows are touched: an acknowledged change records that
somebody acted on it, and deleting that would erase their work.

Reversing is a no-op — the collapsed rows were duplicates of the survivor, and
re-creating them would invent detections that never happened separately.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.scripts.dedup import collapse_duplicate_changes

    deleted = collapse_duplicate_changes(
        apps.get_model("scripts", "ScriptChange"),
        apps.get_model("alerts", "Notification"),
    )
    if deleted:
        print(f"  collapsed {deleted} duplicate change rows")


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0020_merge_multi_step_duplicate_forms"),
        # Notification rows on the deleted changes are repointed at the keeper.
        ("alerts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
