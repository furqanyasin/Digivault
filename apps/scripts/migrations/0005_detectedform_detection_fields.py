import hashlib

from django.db import migrations, models


def backfill_fingerprint(apps, schema_editor):
    """Populate fingerprint for existing rows from their form_action.

    Existing rows are unique per (website, page_url, form_action), so hashing
    the action preserves uniqueness under the new (website, page_url,
    fingerprint) constraint.
    """
    DetectedForm = apps.get_model("scripts", "DetectedForm")
    for form in DetectedForm.objects.all().iterator():
        basis = "|".join(["native", form.form_id or "", form.form_name or "",
                          form.form_action or "", ""])
        form.fingerprint = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]
        form.save(update_fields=["fingerprint"])


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0004_add_critical_severity"),
    ]

    operations = [
        migrations.AddField(
            model_name="detectedform",
            name="detection_type",
            field=models.CharField(
                choices=[
                    ("native", "Native <form>"),
                    ("dom", "Div-based / JS"),
                    ("embedded", "Embedded (iframe)"),
                ],
                default="native",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="detectedform",
            name="provider",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="detectedform",
            name="fingerprint",
            field=models.CharField(db_index=True, default="", max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_fingerprint, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name="detectedform",
            unique_together={("website", "page_url", "fingerprint")},
        ),
    ]
