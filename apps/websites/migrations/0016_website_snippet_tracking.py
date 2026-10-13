from django.db import migrations, models
from django.db.models import Max


def backfill_snippet_activity(apps, schema_editor):
    Website = apps.get_model("websites", "Website")
    ScriptSnapshot = apps.get_model("scripts", "ScriptSnapshot")

    browser_activity = dict(
        ScriptSnapshot.objects.exclude(snippet_version="server-scan")
        .values("website_id")
        .annotate(last_seen=Max("captured_at"))
        .values_list("website_id", "last_seen")
    )
    websites = list(Website.objects.all())
    for website in websites:
        last_seen = browser_activity.get(website.pk)
        website.last_seen_at = last_seen
        website.snippet_first_seen_at = last_seen
        website.snippet_last_seen_at = last_seen
        website.snippet_status = "installed" if last_seen else "not_installed"

    Website.objects.bulk_update(
        websites,
        [
            "last_seen_at",
            "snippet_first_seen_at",
            "snippet_last_seen_at",
            "snippet_status",
        ],
        batch_size=500,
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("websites", "0015_website_wp_connect_last_ack_and_more"),
        ("scripts", "0029_reactivate_wrongly_deactivated_scripts"),
    ]

    operations = [
        migrations.AddField(
            model_name="website",
            name="snippet_first_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="website",
            name="snippet_last_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="website",
            name="snippet_status",
            field=models.CharField(
                choices=[
                    ("not_installed", "Not installed"),
                    ("installed", "Installed"),
                    ("stale", "Stale"),
                ],
                default="not_installed",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_snippet_activity, noop_reverse),
    ]