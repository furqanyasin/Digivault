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
        # ── Script ────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Script",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("src_url", models.TextField()),
                ("src_domain", models.CharField(blank=True, db_index=True, max_length=255)),
                ("provider", models.CharField(db_index=True, default="unknown", max_length=100)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("analytics", "Analytics"),
                            ("advertising", "Advertising"),
                            ("tag_management", "Tag Management"),
                            ("session_recording", "Session Recording"),
                            ("call_tracking", "Call & Conversion Tracking"),
                            ("chat", "Chat & Support"),
                            ("crm", "CRM & Marketing Automation"),
                            ("payment", "Payment"),
                            ("seo", "SEO & Verification"),
                            ("security", "Security & CAPTCHA"),
                            ("performance", "Performance & CDN"),
                            ("social", "Social & Reviews"),
                            ("unknown", "Unknown"),
                        ],
                        db_index=True,
                        default="unknown",
                        max_length=30,
                    ),
                ),
                (
                    "location",
                    models.CharField(
                        choices=[
                            ("head", "Head"),
                            ("body", "Body"),
                            ("footer", "Footer"),
                            ("dynamic", "Dynamic (injected after load)"),
                            ("unknown", "Unknown"),
                        ],
                        default="unknown",
                        max_length=20,
                    ),
                ),
                (
                    "scope",
                    models.CharField(
                        choices=[
                            ("global", "Global (all pages)"),
                            ("page_specific", "Page-specific"),
                            ("one_time", "One-time / test"),
                        ],
                        default="global",
                        max_length=20,
                    ),
                ),
                ("is_async", models.BooleanField(default=False)),
                ("is_defer", models.BooleanField(default=False)),
                ("is_inline", models.BooleanField(default=False)),
                ("inline_hash", models.CharField(blank=True, max_length=64)),
                ("wp_plugin", models.CharField(blank=True, max_length=200)),
                ("wp_post_id", models.IntegerField(blank=True, null=True)),
                ("seen_on_pages", models.JSONField(default=list)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                (
                    "website",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scripts",
                        to="websites.website",
                    ),
                ),
            ],
            options={
                "ordering": ["provider", "src_domain"],
                "unique_together": {("website", "src_url")},
                "indexes": [
                    models.Index(
                        fields=["website", "is_active", "category"],
                        name="scripts_sc_website_active_cat_idx",
                    ),
                    models.Index(
                        fields=["website", "provider"],
                        name="scripts_sc_website_provider_idx",
                    ),
                ],
            },
        ),
        # ── ScriptSnapshot ────────────────────────────────────────────────────
        migrations.CreateModel(
            name="ScriptSnapshot",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("page_url", models.TextField()),
                ("scripts_data", models.JSONField()),
                ("user_agent", models.TextField(blank=True)),
                ("snippet_version", models.CharField(blank=True, max_length=20)),
                ("captured_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "website",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="snapshots",
                        to="websites.website",
                    ),
                ),
            ],
            options={
                "ordering": ["-captured_at"],
                "indexes": [
                    models.Index(
                        fields=["website", "page_url", "-captured_at"],
                        name="scripts_ss_website_page_cap_idx",
                    ),
                ],
            },
        ),
        # ── ScriptChange ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name="ScriptChange",
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
                    "change_type",
                    models.CharField(
                        choices=[
                            ("added", "Script Added"),
                            ("removed", "Script Removed"),
                            ("moved", "Script Moved"),
                            ("url_changed", "Script URL Changed"),
                            ("plugin_changed", "Plugin Source Changed"),
                            ("inline_changed", "Inline Content Changed"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("high", "High"),
                            ("medium", "Medium"),
                            ("low", "Low"),
                        ],
                        default="medium",
                        max_length=10,
                    ),
                ),
                ("description", models.CharField(max_length=500)),
                ("old_value", models.JSONField(blank=True, null=True)),
                ("new_value", models.JSONField(blank=True, null=True)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                (
                    "acknowledged_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="acknowledged_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "script",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="changes",
                        to="scripts.script",
                    ),
                ),
                (
                    "website",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="changes",
                        to="websites.website",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["website", "-created_at"],
                        name="scripts_sc_website_created_idx",
                    ),
                    models.Index(
                        fields=["website", "severity", "acknowledged_at"],
                        name="scripts_sc_website_sev_ack_idx",
                    ),
                ],
            },
        ),
    ]
