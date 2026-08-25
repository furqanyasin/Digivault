"""Turn on weekly SEO scanning for sites left on the old `0` (off) default.

Every website in the database carries `seo_scan_interval_days = 0`, because that
was the field's default and the setting is buried. The result was a dashboard
that looked dead for any site without the tracking snippet installed.

This cannot tell a deliberate "Off" apart from the old default — nothing in the
schema records which it was — so it re-enables both. That is acceptable: the
scan is read-only, runs once a week, and the setting is one click to turn back
off. The reverse leaves data alone rather than switching everyone back off,
since by then some of the 7s will be deliberate choices too.
"""
from django.db import migrations


def enable_weekly_seo(apps, schema_editor):
    Website = apps.get_model("websites", "Website")
    Website.objects.filter(seo_scan_interval_days=0).update(seo_scan_interval_days=7)


class Migration(migrations.Migration):

    dependencies = [
        ("websites", "0012_alter_website_seo_scan_interval_days"),
    ]

    operations = [
        migrations.RunPython(enable_weekly_seo, migrations.RunPython.noop),
    ]
