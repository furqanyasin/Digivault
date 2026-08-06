"""Re-collapse Script rows that a timestamp in the URL path had split apart.

HubSpot serves analytics from `js.hs-analytics.net/analytics/<epoch_ms>/<portal>.js`
and rotates the timestamp every ~30 minutes. That segment counted as identity
until now, so a single portal minted a fresh Script row on every visit — seven
rows for one tag in one day on digilatics.com. Meta's `v=` library version and
`ex_m=` experiment list became volatile in the same change.

Same merge as 0009 and 0016; it is idempotent and keyed on whatever
normalize_script_url currently returns, so re-running it is exactly what a
normalization change needs.

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
        ("scripts", "0016_merge_google_tag_duplicates"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
