from django.db import migrations, models


def enable_where_data_already_exists(apps, schema_editor):
    """Turn the new flag on for sites that are already producing heatmap data.

    The field defaults to off, which is the point of adding it — but flipping
    every existing site off would silently delete a working feature for whoever
    is currently using it, and they would read that as the toggle breaking the
    heatmap rather than as a new default. Any site with a `HeatmapPageStats`
    row has demonstrably been collecting, so it keeps collecting; everything
    else starts off and is enabled deliberately.
    """
    Website = apps.get_model("websites", "Website")
    HeatmapPageStats = apps.get_model("heatmap", "HeatmapPageStats")

    website_ids = set(
        HeatmapPageStats.objects.values_list("website_id", flat=True).distinct()
    )
    if website_ids:
        Website.objects.filter(pk__in=website_ids).update(heatmap_enabled=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("websites", "0016_website_snippet_tracking"),
        ("heatmap", "0005_heatmappagestats_page_height_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="website",
            name="heatmap_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Collect click / move / scroll behaviour for this site's "
                    "heatmap. Off by default — enable it per site."
                ),
            ),
        ),
        migrations.RunPython(enable_where_data_already_exists, noop),
    ]
