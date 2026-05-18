import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("websites", "0001_initial"),
    ]

    operations = [
        # ── DomainInfo ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="DomainInfo",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("registrar", models.CharField(blank=True, max_length=200)),
                ("registered_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("nameservers", models.JSONField(default=list)),
                ("whois_privacy", models.BooleanField(blank=True, null=True)),
                ("auto_renew", models.BooleanField(blank=True, null=True)),
                ("hosting_provider", models.CharField(blank=True, max_length=200)),
                ("hosting_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("server_location", models.CharField(blank=True, max_length=100)),
                ("uses_cloudflare", models.BooleanField(default=False)),
                ("ssl_issuer", models.CharField(blank=True, max_length=200)),
                ("ssl_expires_at", models.DateTimeField(blank=True, null=True)),
                ("ssl_auto_renew", models.BooleanField(blank=True, null=True)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "website",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="domain_info",
                        to="websites.website",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        # ── DomainAlert ───────────────────────────────────────────────────────
        migrations.CreateModel(
            name="DomainAlert",
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
                    "alert_type",
                    models.CharField(
                        choices=[
                            ("domain", "Domain Expiry"),
                            ("ssl", "SSL Expiry"),
                        ],
                        max_length=10,
                    ),
                ),
                ("days_until_expiry", models.IntegerField()),
                ("sent", models.BooleanField(default=False)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                (
                    "domain_info",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="alerts",
                        to="domains.domaininfo",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "unique_together": {("domain_info", "alert_type", "days_until_expiry")},
            },
        ),
    ]
