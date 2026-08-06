"""Re-collapse Script rows that a version in the URL path had split apart.

Microsoft Clarity serves its recorder from `scripts.clarity.ms/<version>/clarity.js`
and ships a release every few days. That segment counted as identity until now,
so one Clarity install minted a fresh Script row — and a high-severity "Unknown
script detected" change — on every vendor release.

A separate migration from 0017 rather than an edit to it: 0017 was written
before `normalize_script_url` learned about version segments, so any database
that already applied it would never re-run and would keep the split rows. The
merge is idempotent and keyed on whatever normalize_script_url returns today,
which is exactly what re-running after a normalization change needs.

Reversing is a no-op: the merged rows are gone, and re-splitting them would
invent history that never meant anything.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.scripts.dedup import merge_duplicate_scripts

    deleted = merge_duplicate_scripts(
        apps.get_model("scripts", "Script"),
        apps.get_model("scripts", "ScriptChange"),
    )
    if deleted:
        print(f"  merged {deleted} duplicate script rows")


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0018_merge_action_url_duplicate_forms"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
