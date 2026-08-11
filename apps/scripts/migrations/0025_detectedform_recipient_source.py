from django.db import migrations, models


def mark_existing_as_page_sourced(apps, schema_editor):
    """Every recipient stored before this migration came from the page markup.

    The WP Connect route is the only other writer and does not exist yet, so
    anything already stored was read from a mailto: action, a data- attribute or
    a hidden field. Leaving these blank would let the next WordPress fetch treat
    them as unknown, which is harmless, but it would also make the UI unable to
    say where a value it is already showing came from.
    """
    DetectedForm = apps.get_model("scripts", "DetectedForm")
    DetectedForm.objects.exclude(recipient_email="").update(recipient_source="page")


class Migration(migrations.Migration):
    dependencies = [
        ("scripts", "0024_detectedform_recipient_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="detectedform",
            name="recipient_source",
            field=models.CharField(
                blank=True,
                choices=[
                    ("page", "Read from the page markup"),
                    ("wordpress", "Reported by WordPress"),
                ],
                default="",
                max_length=10,
            ),
        ),
        migrations.RunPython(
            mark_existing_as_page_sourced,
            migrations.RunPython.noop,
        ),
    ]
