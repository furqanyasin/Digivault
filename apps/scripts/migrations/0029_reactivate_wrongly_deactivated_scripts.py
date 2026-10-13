"""Undo the damage the site-wide deactivation sweep left behind.

Until this release, every ingest ran a site-wide UPDATE that switched off any
globally-scoped script missing from *one page's* observation window. A partial
capture — the first post of a page load before GTM injects, a first-ever visit,
a bounce, or a run of server-side scans that only ever parse static homepage
HTML — therefore deactivated the site's entire runtime-injected marketing stack.
Sites running GTM, GA4, Hotjar, HubSpot and WhatConverts showed a single row.

The pipeline no longer does that, but rows already flipped stay flipped until
the tag happens to be observed again. This restores any script the raw snapshots
say was genuinely on the site recently — evidence, not a blanket re-enable, so a
tag that really was uninstalled stays off.

A tag removed within the window but last observed just before it will come back
here and be deactivated again by the next windowed diff that confirms it. That
is one cycle of churn on a handful of rows, against leaving every affected
customer's Scripts tab wrong until traffic happens to repair it.
"""

from datetime import timedelta

from django.db import migrations
from django.utils import timezone

# Long enough to cover a quiet week of traffic, short enough that a genuinely
# uninstalled tag is unlikely to still appear in the raw snapshots.
_LOOKBACK = timedelta(days=7)


def reactivate(apps, schema_editor):
    from apps.scripts.normalize import normalize_script_url

    Script = apps.get_model("scripts", "Script")
    ScriptSnapshot = apps.get_model("scripts", "ScriptSnapshot")

    since = timezone.now() - _LOOKBACK
    website_ids = (
        Script.objects.filter(is_active=False)
        .values_list("website_id", flat=True)
        .distinct()
    )

    for website_id in list(website_ids):
        seen: set[str] = set()
        rows = ScriptSnapshot.objects.filter(
            website_id=website_id, captured_at__gte=since
        ).values_list("scripts_data", flat=True).iterator(chunk_size=200)
        for scripts_data in rows:
            for script in scripts_data or []:
                src = (script.get("src") or "").strip()
                if src:
                    seen.add(normalize_script_url(src))
        if not seen:
            continue
        Script.objects.filter(
            website_id=website_id, is_active=False, normalized_url__in=seen
        ).update(is_active=True)


def noop(apps, schema_editor):
    """Irreversible by design: which rows were wrong is not recoverable."""


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0028_alter_detectedform_recipient_source"),
    ]

    operations = [
        migrations.RunPython(reactivate, noop),
    ]
