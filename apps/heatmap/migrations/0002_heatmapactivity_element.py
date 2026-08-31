from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("heatmap", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="heatmapactivity",
            name="element",
            field=models.CharField(blank=True, default="", max_length=300),
        ),
    ]
