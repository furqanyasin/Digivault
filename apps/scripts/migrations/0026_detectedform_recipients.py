"""recipient_email (one address) → recipients ({to, cc, bcc})."""

from django.db import migrations, models


def to_recipients(apps, schema_editor):
    """Carry each stored address into the To list of the new shape.

    Values written by earlier versions passed `normalize_recipient_email`, so
    each is already a single lowercase address or "". No re-parsing needed, and
    none is a comma-joined list — that function rejected those outright, which
    is the bug this shape fixes.
    """
    DetectedForm = apps.get_model("scripts", "DetectedForm")
    for form in DetectedForm.objects.all().iterator():
        email = (form.recipient_email or "").strip()
        form.recipients = {"to": [email] if email else [], "cc": [], "bcc": []}
        form.save(update_fields=["recipients"])


def to_recipient_email(apps, schema_editor):
    """Reverse: keep the first To so a rollback isn't a data loss."""
    DetectedForm = apps.get_model("scripts", "DetectedForm")
    for form in DetectedForm.objects.all().iterator():
        to = (form.recipients or {}).get("to") or []
        form.recipient_email = to[0][:254] if to else ""
        form.save(update_fields=["recipient_email"])


class Migration(migrations.Migration):
    dependencies = [
        ("scripts", "0025_detectedform_recipient_source"),
    ]

    # Additive only. `recipient_email` is dropped in a later migration, once a
    # release has run against `recipients` — so this one can be reverted, and the
    # previous release's code still works against the new schema.
    operations = [
        migrations.AddField(
            model_name="detectedform",
            name="recipients",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(to_recipients, to_recipient_email),
    ]
