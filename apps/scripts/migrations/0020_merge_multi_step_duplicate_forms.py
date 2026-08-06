"""Recompute DetectedForm fingerprints without the field set and merge the
duplicates that the field set left behind.

A form's rendered fields are not stable across observations: the snippet posts
several times per page load and again at submit time, and a multi-step form
mounts only the step it is showing. With the fields in the hash, each step
minted its own row — the Forms tab listed the same form twice on one path, the
page-load copies at 0 submits and the submit-time copy holding every
conversion. Counts are summed into the keeper; dropping them would discard real
conversions.

Earlier merge migrations do not re-run on databases that already applied them,
so a fingerprint rule change always needs its own migration.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.scripts.dedup import merge_duplicate_forms

    merge_duplicate_forms(apps.get_model("scripts", "DetectedForm"))


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0019_merge_versioned_path_duplicates"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
