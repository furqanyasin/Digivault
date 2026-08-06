"""Recompute DetectedForm fingerprints with a normalized action and merge the
duplicates the un-normalized action left behind.

`form.action` resolves to the document URL when the attribute is absent, so an
action-less form arrived with a different action for every campaign / referral
URL its page was reached by. Each variant hashed to its own row: the Forms tab
listed the same form several times and split its submission count across the
copies. Counts are summed into the keeper — dropping them would discard real
conversions.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.scripts.dedup import merge_duplicate_forms

    merge_duplicate_forms(apps.get_model("scripts", "DetectedForm"))


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0017_merge_timestamped_script_duplicates"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
