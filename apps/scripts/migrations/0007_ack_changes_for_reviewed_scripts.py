"""One-time cleanup: acknowledge open changes for already-reviewed scripts.

Before this release, marking a script approved/blocked/ignored updated only its
review_status — it never acknowledged the open "Unknown script detected" (HIGH)
change that drove the site to 'critical'. Those sites stayed stuck at critical /
health 55 even after the user triaged every script. Acknowledge those dangling
changes so the status/health self-heal can settle them, then recompute.
"""

from django.db import migrations
from django.utils import timezone


def ack_reviewed_script_changes(apps, schema_editor):
    Script = apps.get_model("scripts", "Script")
    ScriptChange = apps.get_model("scripts", "ScriptChange")

    reviewed_ids = list(
        Script.objects.exclude(review_status="pending").values_list("pk", flat=True)
    )
    if not reviewed_ids:
        return

    open_changes = ScriptChange.objects.filter(
        script_id__in=reviewed_ids, acknowledged_at__isnull=True
    )
    affected_website_ids = list(open_changes.values_list("website_id", flat=True).distinct())
    open_changes.update(acknowledged_at=timezone.now())

    # Recompute status/health for the affected sites. The runtime helpers live on
    # the real models (not historical), and a data migration runs against the
    # current code, so importing them here is safe.
    from apps.scripts.tasks import _update_website_status
    from apps.websites.models import Website as LiveWebsite

    for website in LiveWebsite.objects.filter(pk__in=affected_website_ids):
        _update_website_status(website)
        website.recalculate_health_score()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("scripts", "0006_formsubmissionerror"),
        # Needs the health_score column (added in websites 0004).
        ("websites", "0006_alter_website_seo_scan_interval_days"),
    ]

    operations = [
        migrations.RunPython(ack_reviewed_script_changes, noop),
    ]
