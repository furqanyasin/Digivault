import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        ("websites", "0001_initial"),
    ]

    operations = [
        # ── Credential ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Credential",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("label", models.CharField(max_length=200)),
                (
                    "credential_type",
                    models.CharField(
                        choices=[
                            ("wordpress", "WordPress Admin"),
                            ("cpanel", "cPanel"),
                            ("godaddy", "GoDaddy"),
                            ("namecheap", "Namecheap"),
                            ("hostinger", "Hostinger"),
                            ("cloudflare", "Cloudflare"),
                            ("ftp", "FTP / SFTP"),
                            ("wix", "Wix"),
                            ("webflow", "Webflow"),
                            ("framer", "Framer"),
                            ("shopify", "Shopify"),
                            ("siteground", "SiteGround"),
                            ("bluehost", "Bluehost"),
                            ("wpengine", "WP Engine"),
                            ("kinsta", "Kinsta"),
                            ("custom", "Custom"),
                        ],
                        default="custom",
                        max_length=30,
                    ),
                ),
                ("login_url", models.URLField(blank=True, max_length=500)),
                ("_username", models.BinaryField(blank=True, editable=False)),
                ("_password", models.BinaryField(blank=True, editable=False)),
                ("_notes", models.BinaryField(blank=True, editable=False)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_credentials",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "website",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credentials",
                        to="websites.website",
                    ),
                ),
            ],
            options={
                "ordering": ["credential_type", "label"],
                "indexes": [
                    models.Index(
                        fields=["website", "credential_type"],
                        name="credentials_cr_website_type_idx",
                    ),
                ],
            },
        ),
        # ── CredentialAccessLog ───────────────────────────────────────────────
        migrations.CreateModel(
            name="CredentialAccessLog",
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
                    "action",
                    models.CharField(
                        choices=[
                            ("viewed", "Viewed"),
                            ("copied_password", "Copied Password"),
                            ("edited", "Edited"),
                        ],
                        max_length=20,
                    ),
                ),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                (
                    "credential",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access_logs",
                        to="credentials.credential",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credential_access_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["credential", "-created_at"],
                        name="credentials_cal_credential_idx",
                    ),
                ],
            },
        ),
    ]
