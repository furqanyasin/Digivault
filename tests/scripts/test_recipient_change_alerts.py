"""The ClickUp announcement for a changed form destination."""

from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
from apps.scripts.recipients import build_recipients
from apps.scripts.tasks import deliver_recipient_change_alert
from apps.site_health.models import SiteEvent
from apps.websites.models import Website

PAGE = "https://rca.test/contact"


@pytest.fixture
def form(db):
    owner = User.objects.create_user(email="rca_o@test.com", password="Pass123!")
    team = TeamService.create(name="RCA Agency", owner=owner)
    team.clickup_chat_url = "https://app.clickup.com/9012/chat/r/abc123"
    team.save(update_fields=["clickup_chat_url"])
    website = Website.objects.create(team=team, name="RCA Site", domain="rca.test")
    return DetectedForm.objects.create(
        website=website, page_url=PAGE, fingerprint="fp1",
        form_name="New Form", fields=[],
        recipients=build_recipients(to="new@site.com"),
        recipient_source=DetectedForm.RecipientSource.WORDPRESS,
    )


def _event(form, **overrides):
    details = {
        "form_id": str(form.pk), "form_label": "New Form", "page_url": PAGE,
        "source": "wordpress",
        "old": build_recipients(to="old@site.com"),
        "new": build_recipients(to="new@site.com"),
        "added": ["new@site.com"], "removed": ["old@site.com"], "moved_to_bcc": [],
    }
    details.update(overrides.pop("details", {}))
    return SiteEvent.objects.create(
        website=form.website,
        event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED,
        severity=overrides.pop("severity", SiteEvent.Severity.WARNING),
        summary=overrides.pop("summary", "RCA Site — form “New Form” changed where it delivers"),
        details=details,
    )


@pytest.mark.django_db
class TestDeliverRecipientChangeAlert:
    def test_it_posts_the_old_and_new_addresses(self, form):
        event = _event(form)
        with patch("apps.integrations.chat.notify_problem", return_value=True) as post:
            assert deliver_recipient_change_alert(str(event.pk)) is True

        kwargs = post.call_args.kwargs
        fields = dict(kwargs["fields"])
        assert fields["Was"] == "old@site.com"
        assert fields["Now"] == "new@site.com"
        assert fields["Page"] == PAGE
        assert fields["Form"] == "New Form"
        assert "changed where it delivers" in kwargs["title"]
        assert str(event.pk) in kwargs["subject"]

    def test_cc_and_bcc_are_labelled_in_the_message(self, form):
        event = _event(form, details={
            "new": build_recipients(
                to="lead@site.com", cc="mgr@site.com", bcc="silent@site.com"
            ),
        })
        with patch("apps.integrations.chat.notify_problem", return_value=True) as post:
            deliver_recipient_change_alert(str(event.pk))

        now = dict(post.call_args.kwargs["fields"])["Now"]
        assert "lead@site.com" in now
        assert "mgr@site.com (Cc)" in now
        assert "silent@site.com (Bcc)" in now

    def test_delivering_to_nobody_says_so(self, form):
        event = _event(
            form,
            severity=SiteEvent.Severity.CRITICAL,
            summary="RCA Site — form “New Form” no longer delivers to anyone",
            details={"new": build_recipients(), "added": [], "removed": ["old@site.com"]},
        )
        with patch("apps.integrations.chat.notify_problem", return_value=True) as post:
            deliver_recipient_change_alert(str(event.pk))

        kwargs = post.call_args.kwargs
        assert "no longer delivers to anyone" in kwargs["title"]
        assert dict(kwargs["fields"])["Now"] == "nobody"

    def test_a_missing_event_is_not_an_error(self, form):
        """The purge or a manual delete can race the queued task."""
        with patch("apps.integrations.chat.notify_problem") as post:
            assert deliver_recipient_change_alert(
                "00000000-0000-0000-0000-000000000000"
            ) is False
        post.assert_not_called()

    def test_a_clickup_outage_does_not_raise(self, form):
        """notify_problem swallows its own failures; the task must not add one."""
        event = _event(form)
        with patch("apps.integrations.chat.notify_problem", return_value=False):
            assert deliver_recipient_change_alert(str(event.pk)) is False

    def test_an_unrelated_event_type_is_ignored(self, form):
        other = SiteEvent.objects.create(
            website=form.website, event_type=SiteEvent.EventType.DEPLOYMENT,
            summary="deployed", details={},
        )
        with patch("apps.integrations.chat.notify_problem") as post:
            assert deliver_recipient_change_alert(str(other.pk)) is False
        post.assert_not_called()


@pytest.mark.django_db
class TestWritersHookIn:
    def test_the_wordpress_fetch_records_a_change(self, form):
        """End to end through the real writer, not the helper."""
        from apps.websites.wp_forms import apply_recipients

        with patch("apps.scripts.recipient_changes.transaction.on_commit"):
            apply_recipients(form.website, [{
                "name": "New Form", "to": ["replacement@site.com"],
            }])

        assert SiteEvent.objects.filter(
            event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED
        ).count() == 1
        form.refresh_from_db()
        assert form.recipients["to"] == ["replacement@site.com"]

    def test_a_page_ingest_that_only_confirms_records_nothing(self, form):
        """A pageview that re-observes the same form must not be able to
        supersede WordPress's real answer, and declining to must not raise a
        SiteEvent either.

        `_upsert_form` matches rows by a computed fingerprint, not by the
        fixture's hand-set "fp1" — without lining the two up, this ingest
        would create a brand-new sibling row instead of landing on the
        fixture's, and the test would pass for the wrong reason (a first
        read with no prior source, not the WORDPRESS early-return).
        """
        from apps.scripts.models import DetectedForm
        from apps.scripts.tasks import _upsert_form

        payload = {
            "form_name": "New Form", "detection_type": "native",
            "fields": [{"name": "email"}], "recipients": {},
        }
        form.fingerprint = DetectedForm.compute_fingerprint(payload)
        form.save(update_fields=["fingerprint"])

        _upsert_form(form.website, PAGE, payload)

        assert SiteEvent.objects.filter(
            event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED
        ).count() == 0
        form.refresh_from_db()
        assert form.recipients["to"] == ["new@site.com"]
        assert form.recipient_source == DetectedForm.RecipientSource.WORDPRESS

    def test_a_page_ingest_confirming_an_unchanged_value_records_nothing(self, form):
        """The other guard in `_apply_page_recipients`: once a page-sourced
        value is on record, re-observing the *same* value is a no-op, not a
        change to announce — distinct from the WORDPRESS early-return above,
        which the fixture's row would otherwise always hit first."""
        from apps.scripts.models import DetectedForm
        from apps.scripts.tasks import _upsert_form

        payload = {
            "form_name": "Confirm Form", "detection_type": "native",
            "fields": [{"name": "email"}],
            "recipients": {"to": "confirmed@site.com"},
        }
        _upsert_form(form.website, PAGE, payload)  # first discovery: not news
        assert SiteEvent.objects.filter(
            event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED
        ).count() == 0

        _upsert_form(form.website, PAGE, payload)  # unchanged: still not news

        assert SiteEvent.objects.filter(
            event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED
        ).count() == 0
        confirmed = DetectedForm.objects.get(website=form.website, form_name="Confirm Form")
        assert confirmed.recipient_source == DetectedForm.RecipientSource.PAGE
