"""Normalize DetectedForm page URLs, recompute hardened fingerprints, and
merge rows that were duplicates caused by URL variants or rotating
nonce/honeypot fields."""

from collections import defaultdict

from django.db import migrations


def forwards(apps, schema_editor):
    # Static helpers with no model state — safe to use in a migration.
    from apps.scripts.models import DetectedForm as RealDetectedForm
    from apps.scripts.normalize import normalize_page_url

    detected_form = apps.get_model("scripts", "DetectedForm")

    groups = defaultdict(list)
    for form in detected_form.objects.all().order_by("first_seen_at"):
        page = normalize_page_url(form.page_url)
        fingerprint = RealDetectedForm.compute_fingerprint({
            "detection_type": form.detection_type,
            "form_id": form.form_id,
            "form_name": form.form_name,
            "form_action": form.form_action,
            "fields": form.fields or [],
        })
        groups[(form.website_id, page, fingerprint)].append(form)

    for (_, page, fingerprint), dupes in groups.items():
        keeper, rest = dupes[0], dupes[1:]
        last_seen = max((d.last_seen_at for d in dupes if d.last_seen_at), default=None)
        for dup in rest:
            dup.delete()
        detected_form.objects.filter(pk=keeper.pk).update(
            page_url=page,
            fingerprint=fingerprint,
            last_seen_at=last_seen,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0010_script_unique_normalized"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
