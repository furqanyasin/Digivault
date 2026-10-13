"""Merge the duplicate DetectedForm rows the scan/browser action split created.

`form.action` in a browser resolves an absent or relative action attribute
against the document, so the tracking snippet reported
`https://site.com/contact-us` for a form whose markup says nothing at all, while
the server-side scan — which reads the raw attribute out of static HTML —
reported `""`. The action is part of the fingerprint, so one form stored two
rows on one page: the Forms tab listed it twice, split its submissions between
the copies, and rendered whichever sorted first, which is how a live contact
form displayed "Action: None" and "Fields (0)" beside seven real fields.

`resolve_form_action` now puts every source on the browser's rule. This merges
what the old rule already stored — summing submission counts, since both halves
hold real conversions, and keeping the richest field list rather than the
earliest row's, which on a scan/browser pair is usually the empty one.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.scripts.dedup import merge_duplicate_forms

    merge_duplicate_forms(apps.get_model("scripts", "DetectedForm"))


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0031_merge_identity_churn_duplicates"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
