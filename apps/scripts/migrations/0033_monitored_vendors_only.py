"""Keep only the monitored vendors' tags, one row per installed tag.

Two changes land alongside this, and both only reach new ingest on their own.

**Merge.** `normalize_script_url` now keys a monitored vendor's files by the tag
they belong to (`monitored.tag_identity`): HubSpot's analytics, cookie-banner and
forms files collapse onto `js.hs-scripts.com/<portal>.js`, `gtag/destination?id=X`
onto `gtag/js?id=X`, the GoHighLevel chat-widget files onto its loader. The rows
already split that way are merged here — the keeper absorbs the union of
`seen_on_pages`, the strongest review verdict and `is_active` if any was active,
and ScriptChange rows are repointed — and the open changes that now describe one
tag several times are collapsed.

**Retire.** `_should_track_script` now keeps only Google, HubSpot, Hotjar,
WhatConverts, ClickUp and GoHighLevel, plus high-confidence injected code. Every
other row — Meta Pixel, Clarity, TikTok, consent banners, unknown third parties,
and the monitored vendors' own sub-resources that did not merge onto a tag — is
deactivated and its open changes acknowledged, so the alert list stops showing
scripts the product no longer reports on. Rows are kept, not deleted, so the
history is still there if a vendor is added to the list later.

Reversing is a no-op for the same reasons as 0031.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from django.utils import timezone

    from apps.scripts.dedup import collapse_duplicate_changes, merge_duplicate_scripts
    from apps.scripts.monitored import tag_identity
    from apps.scripts.suspicion import SEVERITY_HIGH, analyse

    script_model = apps.get_model("scripts", "Script")
    change_model = apps.get_model("scripts", "ScriptChange")
    notification_model = apps.get_model("alerts", "Notification")

    merged = merge_duplicate_scripts(script_model, change_model)
    if merged:
        print(f"  merged {merged} script rows onto their tag")
    collapsed = collapse_duplicate_changes(change_model, notification_model)
    if collapsed:
        print(f"  collapsed {collapsed} duplicate change rows")

    retire_pks = [
        script.pk
        for script in script_model.objects.select_related("website").only(
            "pk", "src_url", "website__domain"
        )
        if tag_identity(script.src_url) is None
        and analyse(script.src_url, site_domain=script.website.domain).severity
        != SEVERITY_HIGH
    ]
    if retire_pks:
        script_model.objects.filter(pk__in=retire_pks, is_active=True).update(
            is_active=False
        )
        acknowledged = change_model.objects.filter(
            script_id__in=retire_pks, acknowledged_at__isnull=True
        ).update(acknowledged_at=timezone.now())
        print(
            f"  retired {len(retire_pks)} unmonitored script rows "
            f"({acknowledged} open changes acknowledged)"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("scripts", "0032_merge_document_action_forms"),
        ("alerts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
