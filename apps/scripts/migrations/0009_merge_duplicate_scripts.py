"""Backfill Script.normalized_url and merge rows that differ only by
volatile cache-buster query params (?ver=, ?nonce=, ...)."""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.scripts.dedup import merge_duplicate_scripts

    script_model = apps.get_model("scripts", "Script")
    script_change_model = apps.get_model("scripts", "ScriptChange")
    merge_duplicate_scripts(script_model, script_change_model)


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0008_script_normalized_url"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
