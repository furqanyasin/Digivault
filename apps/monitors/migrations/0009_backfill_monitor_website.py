from django.db import migrations


def backfill_monitor_website(apps, schema_editor):
    """Link existing auto-provisioned monitors to their website by matching
    the monitor URL against the website domain (same team)."""
    Monitor = apps.get_model("monitors", "Monitor")
    Website = apps.get_model("websites", "Website")
    for w in Website.objects.all():
        domain = (w.domain or "").replace("https://", "").replace("http://", "").strip("/")
        if not domain:
            continue
        Monitor.objects.filter(
            team_id=w.team_id, website__isnull=True, url__icontains=domain
        ).update(website_id=w.id)


class Migration(migrations.Migration):
    dependencies = [
        ("monitors", "0008_monitor_website"),
        ("websites", "0007_website_notification_channel"),
    ]
    operations = [migrations.RunPython(backfill_monitor_website, migrations.RunPython.noop)]
