"""Re-collapse Script rows that the widened volatile-param list made duplicates.

gtag/GTM append their container version (`gtm=4e6840`) and per-request consent
flags to their own src, and asset pipelines put content hashes in filenames
(`modules.75bf3488a101739acfe9.js`). Both were part of a script's identity until
now, so one tag had been minting a fresh Script row on every publish. Widening
what counts as volatile makes the existing rows collide on
(website, normalized_url) — this merges them.

Same merge as 0009; it is idempotent and keyed on whatever normalize_script_url
currently returns, so re-running it is exactly what a normalization change needs.

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
        ("scripts", "0015_jserror"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
