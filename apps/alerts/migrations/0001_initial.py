import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        ("scripts", "0001_initial"),
        ("websites", "0001_initial"),
    ]

    operations = [
        # ── AlertRule ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="AlertRule",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "channel",
                    models.CharField(
                        choices=[
                            ("email", "Email"),
                            ("slack", "Slack"),
                            ("sms", "SMS"),
                            ("in_app", "In-App"),
                        ],
                        max_length=10,
                    ),
                ),
                (
                    "min_severity",
                    models.CharField(
                        choices=[
                            ("high", "High only"),
                            ("medium", "Medium & above"),
                            ("low", "All"),
                        ],
                        default="medium",
                        max_length=10,
                    ),
                ),
                ("change_types", models.JSONField(default=list)),
                (
                    "delivery_mode",
                    models.CharField(
                        choices=[
                            ("immediate", "Immediate"),
                            ("hourly_digest", "Hourly Digest"),
                            ("daily_digest", "Daily Digest"),
                        ],
                        default="immediate",
                        max_length=20,
                    ),
                ),
                ("slack_webhook_url", models.URLField(blank=True, max_length=500)),
                ("sms_phone_number", models.CharField(blank=True, max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="alert_rules",
                        to="accounts.team",
                    ),
                ),
                (
                    "website",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="alert_rules",
                        to="websites.website",
                    ),
                ),
            ],
            options={
                "ordering": ["team", "channel"],
            },
        ),
        # ── Notification ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Notification",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "channel",
                    models.CharField(
                        choices=[
                            ("email", "Email"),
                            ("slack", "Slack"),
                            ("sms", "SMS"),
                            ("in_app", "In-App"),
                        ],
                        max_length=10,
                    ),
                ),
                (
                    "delivery_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=10,
                    ),
                ),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
                ("digest_period_start", models.DateTimeField(blank=True, null=True)),
                ("read", models.BooleanField(default=False)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                (
                    "rule",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="notifications",
                        to="alerts.alertrule",
                    ),
                ),
                (
                    "script_change",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="notifications",
                        to="scripts.scriptchange",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="accounts.team",
                    ),
                ),
                (
                    "website",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="websites.website",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["team", "read", "-created_at"],
                        name="alerts_no_team_read_created_idx",
                    ),
                    models.Index(
                        fields=["team", "delivery_status"],
                        name="alerts_no_team_status_idx",
                    ),
                ],
            },
        ),
    ]
