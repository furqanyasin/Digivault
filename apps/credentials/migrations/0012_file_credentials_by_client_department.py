"""File every existing credential under its client and department.

`client` comes from the credential's website; `department` from its type, using
a frozen copy of `Credential.DEFAULT_DEPARTMENT` (a migration must not import
live code that will change after it has run). Only blank values are filled, so
re-running this — or running it after someone has filed things by hand — never
moves a credential.

Filing a credential is a permission, not a label: once an owner tags a group
with a department, its members see everything filed there. Nothing changes on
deploy, because no group has a department yet.
"""

from django.db import migrations

_DEFAULT_DEPARTMENT = {
    **{t: "dev" for t in (
        "wordpress", "wordpress_app_password", "cpanel", "godaddy", "namecheap",
        "hostinger", "cloudflare", "ftp", "wix", "webflow", "framer", "shopify",
        "siteground", "bluehost", "wpengine", "kinsta",
    )},
}


def forwards(apps, schema_editor):
    Credential = apps.get_model("credentials", "Credential")

    for cred in (
        Credential.objects.filter(client__isnull=True, website__client__isnull=False)
        .select_related("website")
        .only("id", "website__client_id")
        .iterator()
    ):
        Credential.objects.filter(pk=cred.pk).update(client_id=cred.website.client_id)

    for credential_type, department in _DEFAULT_DEPARTMENT.items():
        Credential.objects.filter(
            department="", credential_type=credential_type
        ).update(department=department)


class Migration(migrations.Migration):

    dependencies = [
        ("credentials", "0011_totp_client_department"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
