from django.db import migrations

# Heatmap became a grantable section. `effective_features` returns a stored
# feature_access list verbatim once it is non-empty, so adding the key without
# this backfill would silently revoke Heatmap from every member a manager had
# ever fine-tuned. `custom` members are skipped: their access is granted
# deliberately, one chip at a time.
FEATURE = "heatmap"


def add_heatmap(apps, schema_editor):
    TeamMembership = apps.get_model("accounts", "TeamMembership")
    for m in TeamMembership.objects.exclude(role="custom").iterator():
        access = m.feature_access or []
        if not access or FEATURE in access:
            continue
        m.feature_access = [*access, FEATURE]
        m.save(update_fields=["feature_access"])


def remove_heatmap(apps, schema_editor):
    TeamMembership = apps.get_model("accounts", "TeamMembership")
    for m in TeamMembership.objects.iterator():
        access = m.feature_access or []
        if FEATURE not in access:
            continue
        m.feature_access = [k for k in access if k != FEATURE]
        m.save(update_fields=["feature_access"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_team_clickup_chat_url"),
    ]

    operations = [
        migrations.RunPython(add_heatmap, remove_heatmap),
    ]
