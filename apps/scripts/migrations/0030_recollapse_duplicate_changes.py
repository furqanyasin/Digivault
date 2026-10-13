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
        ("scripts", "0029_reactivate_wrongly_deactivated_scripts"),
        ("alerts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]