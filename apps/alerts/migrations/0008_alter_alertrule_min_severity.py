from django.db import migrations, models


class Migration(migrations.Migration):
    """Add `critical` to the rule minimums.

    Choices-only, so no data changes: every stored value ("high", "medium",
    "low") is still valid. It exists because `ScriptChange.Severity` has always
    offered `critical` while this list did not, and a vocabulary defined twice
    is how `critical` ended up rankable by the model and unrankable by the
    matcher.
    """

    dependencies = [
        ('alerts', '0007_notification_site_event'),
    ]

    operations = [
        migrations.AlterField(
            model_name='alertrule',
            name='min_severity',
            field=models.CharField(
                choices=[
                    ('critical', 'Critical only'),
                    ('high', 'High & above'),
                    ('medium', 'Medium & above'),
                    ('low', 'All'),
                ],
                default='medium',
                max_length=10,
            ),
        ),
    ]
