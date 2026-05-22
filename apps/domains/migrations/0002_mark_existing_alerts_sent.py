from django.db import migrations


def mark_existing_sent(apps, schema_editor):
    """Mark every pre-existing DomainAlert as sent.

    Delivery was not wired up before this release, so historical alerts have
    sent=False. Without this, the first domain check after deploy would send a
    burst of stale expiry notifications. Only thresholds crossed from now on
    should be delivered.
    """
    from django.utils import timezone

    DomainAlert = apps.get_model("domains", "DomainAlert")
    DomainAlert.objects.filter(sent=False).update(sent=True, sent_at=timezone.now())


def reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("domains", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(mark_existing_sent, reverse),
    ]
