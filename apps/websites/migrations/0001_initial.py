import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Website",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=200)),
                ("domain", models.CharField(max_length=255)),
                (
                    "platform",
                    models.CharField(
                        choices=[
                            ("wordpress", "WordPress"),
                            ("webflow", "Webflow"),
                            ("wix", "Wix"),
                            ("framer", "Framer"),
                            ("shopify", "Shopify"),
                            ("squarespace", "Squarespace"),
                            ("custom", "Custom"),
                            ("other", "Other"),
                        ],
                        default="other",
                        max_length=20,
                    ),
                ),
                (
                    "site_id",
                    models.CharField(blank=True, db_index=True, max_length=64, unique=True),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("inactive", "Inactive"),
                            ("warning", "Warning"),
                            ("critical", "Critical"),
                        ],
                        default="active",
                        max_length=20,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("tags", models.JSONField(blank=True, default=list)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="websites",
                        to="accounts.team",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "indexes": [
                    models.Index(fields=["team", "status"], name="websites_we_team_id_status_idx"),
                    models.Index(fields=["domain"], name="websites_we_domain_idx"),
                ],
            },
        ),
    ]
