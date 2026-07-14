"""Client overhaul (client feedback round):

- statuses become active / paused / offboarded (inactive → offboarded)
- support_tier becomes tier (premium→gold, standard→silver, basic→bronze)
- adds access level, departments, conditional Other hosting, domain renewal,
  notification toggles
- drops Contract / Migration / ClickUp / Comments fields
"""

from django.db import migrations, models


def forwards(apps, schema_editor):
    client = apps.get_model("clients", "Client")
    client.objects.filter(status="inactive").update(status="offboarded")
    client.objects.filter(tier="premium").update(tier="gold")
    client.objects.filter(tier="standard").update(tier="silver")
    client.objects.filter(tier="basic").update(tier="bronze")


def backwards(apps, schema_editor):
    client = apps.get_model("clients", "Client")
    client.objects.filter(status__in=["offboarded", "paused"]).update(status="inactive")
    client.objects.filter(tier="gold").update(tier="premium")
    client.objects.filter(tier="silver").update(tier="standard")
    client.objects.filter(tier="bronze").update(tier="basic")


class Migration(migrations.Migration):

    dependencies = [
        ("clients", "0004_backfill_hosting_to_websites"),
    ]

    operations = [
        migrations.RenameField(
            model_name="client", old_name="support_tier", new_name="tier"
        ),
        migrations.AlterField(
            model_name="client",
            name="tier",
            field=models.CharField(
                blank=True,
                choices=[
                    ("gold", "Gold"),
                    ("silver", "Silver"),
                    ("bronze", "Bronze"),
                    ("", "None"),
                ],
                default="",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="client",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("paused", "Paused"),
                    ("offboarded", "Offboarded"),
                ],
                db_index=True,
                default="active",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="hosting_platform_other",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="client",
            name="domain_renewal_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="client",
            name="website_access_level",
            field=models.CharField(
                blank=True,
                choices=[
                    ("full_admin", "Full admin"),
                    ("delegate", "Delegate access"),
                    ("none", "No access"),
                    ("", "Unknown"),
                ],
                default="",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="departments",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="client",
            name="notify_desktop",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="client",
            name="notify_email",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="client", name="migration_status"),
        migrations.RemoveField(model_name="client", name="csm_migration_confirmation"),
        migrations.RemoveField(model_name="client", name="comments"),
        migrations.RemoveField(model_name="client", name="contract_renewal_date"),
        migrations.RemoveField(model_name="client", name="clickup_task_id"),
        migrations.RemoveField(model_name="client", name="clickup_synced_at"),
    ]
