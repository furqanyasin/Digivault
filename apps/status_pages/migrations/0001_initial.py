import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0002_alter_user_managers_alter_user_groups_and_more"),
        ("monitors", "0002_add_notification_channel_and_rule"),
    ]

    operations = [
        migrations.CreateModel(
            name="StatusPage",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=100, unique=True)),
                ("description", models.TextField(blank=True)),
                ("allow_indexing", models.BooleanField(default=False, help_text="Allow search engines to index this page. Off by default.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_pages", to="accounts.team")),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="StatusPageMonitor",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("display_name", models.CharField(blank=True, help_text="Optional override name shown on the public page.", max_length=200)),
                ("display_order", models.PositiveIntegerField(default=0)),
                ("monitor", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_page_entries", to="monitors.monitor")),
                ("status_page", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="monitors", to="status_pages.statuspage")),
            ],
            options={"ordering": ["display_order", "display_name"], "unique_together": {("status_page", "monitor")}},
        ),
    ]
