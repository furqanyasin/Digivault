"""Re-collapse Script rows that Google's tag runtime params had split apart.

`normalize_script_url` stripped volatile query params by denylist. Google ships
new ones on its own schedule — `cst`, `_slc`, `sst`, `pscdl`, `_ip`, `num`,
`frm`, `z` have all appeared on `gtag/js` — and each unlisted one became part of
the script's identity, so one GA4 property could hold nine Script rows. The
denylist is now an allowlist for those hosts (`_IDENTITY_PARAMS`), which fixes
new ingest; the rows already minted have to be merged.

A separate migration from 0017/0019/0023 rather than an edit to them: a database
that already applied those will never re-run them, and would keep its split
rows. The merge is idempotent and keyed on whatever `normalize_script_url`
returns today, which is exactly what re-running after a normalization change
needs.

The keeper absorbs the union of `seen_on_pages`, the strongest review verdict
and the latest raw `src_url`; `ScriptChange` FKs are repointed. So a GA4 tag
someone had already approved stays approved instead of the merge resetting nine
rows' worth of review work to pending.

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
        ("scripts", "0026_detectedform_recipients"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
