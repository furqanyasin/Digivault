"""Turn department access into folders, keeping exactly the access people had.

Department access (a group tagged "seo" saw every credential filed under the
seo department) is replaced by user-made folders with group grants — the
LastPass shared-folder model. For every department some group is tagged with,
this creates a folder of that name in the team, files that department's
unfiled credentials into it, and gives each tagged group a folder grant with
the same `can_view_password`. Then it clears the group tags.

Departments nobody was granted are left alone: no folder is invented for them,
because folders are meant to be made by people, not derived.
"""

from django.db import migrations

_LABELS = {
    "seo": "SEO",
    "ads": "Ads",
    "dev": "Development",
    "content": "Content",
    "lead_insight": "Lead Insight",
    "social_media": "Social Media",
}


def forwards(apps, schema_editor):
    SubTeam = apps.get_model("accounts", "SubTeam")
    VaultFolder = apps.get_model("credentials", "VaultFolder")
    Credential = apps.get_model("credentials", "Credential")
    Grant = apps.get_model("credentials", "SubTeamCredentialGrant")

    for group in SubTeam.objects.exclude(department=""):
        name = _LABELS.get(group.department, group.department.replace("_", " ").title())
        folder = (
            VaultFolder.objects.filter(team_id=group.team_id, name__iexact=name).first()
            or VaultFolder.objects.create(team_id=group.team_id, name=name)
        )
        Credential.objects.filter(
            team_id=group.team_id, department=group.department, folder__isnull=True
        ).update(folder=folder)
        Grant.objects.get_or_create(
            sub_team=group,
            scope="folder",
            folder=folder,
            defaults={"can_view_password": group.department_can_view_password},
        )
        group.department = ""
        group.department_can_view_password = False
        group.save(update_fields=["department", "department_can_view_password"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_subteam_department_and_more"),
        ("credentials", "0016_vault_folders"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
