"""Raise the default check interval to 15 minutes and slow existing monitors.

Every uptime check leaves the platform from one public IP. At a 5-minute (or
worse, 30-second) interval across the whole client fleet, that IP looks like a
scanner to Cloudflare/Sucuri/AWS WAF — which is how it ends up challenged or
blackholed, producing bogus "down" readings for sites that are perfectly fine.

Monitors already polling slower than 15 minutes are left alone.
"""

from django.db import migrations, models

FIFTEEN_MINUTES = 900


def slow_down_frequent_monitors(apps, schema_editor):
    Monitor = apps.get_model("monitors", "Monitor")
    Monitor.objects.filter(check_interval__lt=FIFTEEN_MINUTES).update(
        check_interval=FIFTEEN_MINUTES
    )


def noop_reverse(apps, schema_editor):
    """Intentionally not restoring the old intervals — they are what caused the
    blocking, and the original per-monitor values are not recoverable anyway."""


class Migration(migrations.Migration):

    dependencies = [
        ("monitors", "0009_backfill_monitor_website"),
    ]

    operations = [
        migrations.AlterField(
            model_name="monitor",
            name="check_interval",
            field=models.PositiveIntegerField(
                choices=[
                    (30, "Every 30 seconds"),
                    (60, "Every 1 minute"),
                    (120, "Every 2 minutes"),
                    (300, "Every 5 minutes"),
                    (600, "Every 10 minutes"),
                    (900, "Every 15 minutes"),
                    (1800, "Every 30 minutes"),
                    (3600, "Every hour"),
                ],
                default=900,
            ),
        ),
        migrations.RunPython(slow_down_frequent_monitors, noop_reverse),
    ]
