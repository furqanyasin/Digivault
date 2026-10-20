from django.db import migrations


class Migration(migrations.Migration):
    """The "by Digi" names came from the agency this was first built for."""

    dependencies = [
        ("clients", "0006_alter_client_website_access_level"),
    ]

    operations = [
        migrations.RenameField("client", "website_built_by_digi", "website_built_by_us"),
        migrations.RenameField("client", "website_maintained_by_digi", "website_maintained_by_us"),
    ]
