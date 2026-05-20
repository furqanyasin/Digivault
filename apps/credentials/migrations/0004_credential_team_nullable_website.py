import django.db.models.deletion
from django.db import migrations, models


def populate_team(apps, schema_editor):
    Credential = apps.get_model("credentials", "Credential")
    Website = apps.get_model("websites", "Website")
    for cred in Credential.objects.filter(website__isnull=False):
        try:
            website = Website.objects.get(pk=cred.website_id)
            cred.team_id = website.team_id
            cred.save(update_fields=["team_id"])
        except Website.DoesNotExist:
            pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("credentials", "0003_credential_username_hash"),
        ("websites", "0001_initial"),
    ]

    operations = [
        # Step 1: add team as nullable so existing rows are valid
        migrations.AddField(
            model_name="credential",
            name="team",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="credentials",
                to="accounts.team",
            ),
        ),
        # Step 2: fill team_id from website.team_id for every existing credential
        migrations.RunPython(populate_team, migrations.RunPython.noop),
        # Step 3: make team NOT NULL
        migrations.AlterField(
            model_name="credential",
            name="team",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="credentials",
                to="accounts.team",
            ),
        ),
        # Step 4: website becomes optional (SET_NULL so orphans stay in vault)
        migrations.AlterField(
            model_name="credential",
            name="website",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="credentials",
                to="websites.website",
            ),
        ),
        # Step 5: swap indexes
        migrations.RemoveIndex(
            model_name="credential",
            name="credentials_website_a1a046_idx",
        ),
        migrations.AddIndex(
            model_name="credential",
            index=models.Index(
                fields=["team", "credential_type"],
                name="credentials_team_type_idx",
            ),
        ),
    ]
