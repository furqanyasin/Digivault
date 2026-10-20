"""The recipient_email → recipients migration must not lose an address."""

import pytest
from django.apps import apps as django_apps
from django.db.migrations.executor import MigrationExecutor
from django.db import connection


@pytest.mark.django_db(transaction=True)
class TestRecipientsBackfill:
    def test_an_existing_address_becomes_a_to_list(self):
        """Rows written before this migration hold one address in a CharField.

        Dropping the column without carrying the value over would silently
        empty the Goes to column for every form Stacks Monitor had already learned.
        """
        executor = MigrationExecutor(connection)
        app = "scripts"

        # Rewind to just before the new migration.
        executor.migrate([(app, "0025_detectedform_recipient_source")])
        old = executor.loader.project_state(
            [(app, "0025_detectedform_recipient_source")]
        ).apps

        # Team/Website aren't touched by this migration and stay at the real
        # (fully-migrated) schema throughout, since only the "scripts" app was
        # rewound above — `old`'s historical state only walks the ancestors of
        # the scripts 0025 node, which predates several accounts migrations
        # (e.g. Team.clickup_list_id), so building Team/Website from `old`
        # would INSERT rows missing NOT NULL columns the real table has.
        # Pulling them from the live app registry instead matches the actual
        # DB schema and keeps this test only about DetectedForm's migration.
        User = django_apps.get_model("accounts", "User")
        Team = django_apps.get_model("accounts", "Team")
        Website = django_apps.get_model("websites", "Website")
        DetectedForm = old.get_model(app, "DetectedForm")

        owner = User.objects.create(
            email="backfill-owner@test.com", username="backfill-owner@test.com"
        )
        team = Team.objects.create(name="Backfill Team", owner=owner)
        website = Website.objects.create(team=team, name="S", domain="backfill.test")
        # `website_id=` rather than `website=` — `website` is the live model
        # (see the comment above), but `DetectedForm` here is the historical
        # model tied to the pre-migration app registry, and Django's FK
        # descriptor rejects an instance of a different model class outright.
        with_email = DetectedForm.objects.create(
            website_id=website.id, page_url="https://backfill.test/a",
            fingerprint="f1", recipient_email="info@site.com",
            recipient_source="page", fields=[],
        )
        without = DetectedForm.objects.create(
            website_id=website.id, page_url="https://backfill.test/b",
            fingerprint="f2", recipient_email="", fields=[],
        )

        # Apply the new migration.
        executor = MigrationExecutor(connection)
        executor.migrate([(app, "0026_detectedform_recipients")])
        new = executor.loader.project_state(
            [(app, "0026_detectedform_recipients")]
        ).apps
        Migrated = new.get_model(app, "DetectedForm")

        assert Migrated.objects.get(pk=with_email.pk).recipients == {
            "to": ["info@site.com"], "cc": [], "bcc": [],
        }
        assert Migrated.objects.get(pk=without.pk).recipients == {
            "to": [], "cc": [], "bcc": [],
        }
