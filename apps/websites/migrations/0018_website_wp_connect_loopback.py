from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("websites", "0017_website_heatmap_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="website",
            name="wp_connect_loopback_status",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="website",
            name="wp_connect_loopback_ms",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="website",
            name="wp_connect_loopback_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
