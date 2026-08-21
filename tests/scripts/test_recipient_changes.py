"""Deciding whether a recipient change is worth telling the team about."""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
from apps.scripts.recipients import build_recipients
from apps.scripts.recipient_changes import (
    describe_recipient_change,
    record_recipient_change,
)
from apps.site_health.models import SiteEvent
from apps.websites.models import Website

PAGE = "https://rc.test/contact"


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="rc_o@test.com", password="Pass123!")
    team = TeamService.create(name="RC Agency", owner=owner)
    return Website.objects.create(team=team, name="RC Site", domain="rc.test")


@pytest.fixture
def form(website):
    return DetectedForm.objects.create(
        website=website, page_url=PAGE, fingerprint="fp1",
        form_name="New Form", fields=[],
        recipients=build_recipients(to="old@site.com"),
        recipient_source=DetectedForm.RecipientSource.WORDPRESS,
    )


class TestDescribeRecipientChange:
    def test_an_identical_set_is_not_a_change(self):
        a = build_recipients(to="a@site.com")
        assert describe_recipient_change(a, build_recipients(to="a@site.com")) is None

    def test_a_reordered_set_is_not_a_change(self):
        assert describe_recipient_change(
            build_recipients(to="a@site.com, b@site.com"),
            build_recipients(to="b@site.com, a@site.com"),
        ) is None

    def test_first_discovery_is_not_a_change(self):
        """Empty → populated is detection catching up, not an edit to the form.

        Every form Digivault already knows about goes through this transition
        the first time WP Connect answers; announcing it would post once per
        form on the whole estate.
        """
        assert describe_recipient_change(
            build_recipients(), build_recipients(to="a@site.com")
        ) is None

    def test_a_replaced_address_is_a_warning(self):
        change = describe_recipient_change(
            build_recipients(to="old@site.com"), build_recipients(to="new@site.com")
        )
        assert change["severity"] == SiteEvent.Severity.WARNING
        assert change["added"] == ["new@site.com"]
        assert change["removed"] == ["old@site.com"]

    def test_losing_every_address_is_critical(self):
        """The form still exists and now delivers to nobody — the worst case,
        and silent from the visitor's side."""
        change = describe_recipient_change(
            build_recipients(to="lead@site.com"), build_recipients()
        )
        assert change["severity"] == SiteEvent.Severity.CRITICAL
        assert change["summary_verb"] == "no longer delivers to anyone"

    def test_an_added_bcc_is_reported_as_such(self):
        """The one destination a client can add that nobody else can see."""
        change = describe_recipient_change(
            build_recipients(to="lead@site.com"),
            build_recipients(to="lead@site.com", bcc="silent@elsewhere.com"),
        )
        assert change["severity"] == SiteEvent.Severity.WARNING
        assert change["added"] == ["silent@elsewhere.com"]
        assert change["moved_to_bcc"] == []

    def test_moving_a_to_into_bcc_is_flagged_as_a_move(self):
        """The address still receives mail, so it is neither added nor removed —
        but it has stopped being a visible destination."""
        change = describe_recipient_change(
            build_recipients(to="lead@site.com"), build_recipients(bcc="lead@site.com")
        )
        assert change["moved_to_bcc"] == ["lead@site.com"]
        assert change["severity"] == SiteEvent.Severity.WARNING

    def test_a_removed_cc_is_only_information(self):
        change = describe_recipient_change(
            build_recipients(to="lead@site.com", cc="watcher@site.com"),
            build_recipients(to="lead@site.com"),
        )
        assert change["severity"] == SiteEvent.Severity.INFO


@pytest.mark.django_db
class TestRecordRecipientChange:
    def test_a_change_within_one_source_is_recorded(self, form):
        form.recipients = build_recipients(to="new@site.com")
        form.save(update_fields=["recipients"])
        event = record_recipient_change(
            form,
            old_recipients=build_recipients(to="old@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        )
        assert event is not None
        assert event.event_type == SiteEvent.EventType.FORM_RECIPIENTS_CHANGED
        assert event.website_id == form.website_id
        assert "New Form" in event.summary
        assert event.details["page_url"] == PAGE
        assert event.details["old"]["to"] == ["old@site.com"]
        assert event.details["new"]["to"] == ["new@site.com"]

    def test_a_source_upgrade_is_not_a_change(self, form):
        """page → wordpress reporting a different address is a better *read* of
        the same form, not an edit to it. Announcing it would fire for every
        form on the estate the first time WP Connect answers."""
        assert record_recipient_change(
            form,
            old_recipients=build_recipients(to="guessed@site.com"),
            old_source=DetectedForm.RecipientSource.PAGE,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        ) is None
        assert SiteEvent.objects.count() == 0

    def test_a_first_read_with_no_prior_source_is_not_a_change(self, form):
        """Isolates the `not old_source` clause: both sides falsy (equal), so
        this cannot be passing because the sources merely differ — that case
        is `test_a_source_upgrade_is_not_a_change`, above."""
        assert record_recipient_change(
            form,
            old_recipients=build_recipients(),
            old_source="",
            new_source="",
        ) is None

    def test_the_same_transition_is_suppressed_inside_the_cooldown(self, form):
        """A form flipping between two addresses must not post every night."""
        kwargs = dict(
            old_recipients=build_recipients(to="old@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        )
        form.recipients = build_recipients(to="new@site.com")
        form.save(update_fields=["recipients"])
        assert record_recipient_change(form, **kwargs) is not None
        assert record_recipient_change(form, **kwargs) is None
        assert SiteEvent.objects.count() == 1

    def test_a_reordered_repeat_of_the_same_transition_is_suppressed(self, form):
        """A WordPress poll can return the same address set in a different
        order across requests. jsonb equality on the raw `old`/`new` dicts is
        array-order-sensitive, so the cooldown match has to go through the
        sorted `transition_key`, not those dicts directly, or this would slip
        past as a "new" transition and re-post inside the window."""
        form.recipients = build_recipients(to="new@site.com, spare@site.com")
        form.save(update_fields=["recipients"])
        first = record_recipient_change(
            form,
            old_recipients=build_recipients(to="old@site.com, extra@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        )
        assert first is not None

        # Same addresses, reordered on both sides.
        form.recipients = build_recipients(to="spare@site.com, new@site.com")
        form.save(update_fields=["recipients"])
        repeat = record_recipient_change(
            form,
            old_recipients=build_recipients(to="extra@site.com, old@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        )
        assert repeat is None
        assert SiteEvent.objects.count() == 1

    def test_a_different_transition_is_not_suppressed(self, form):
        form.recipients = build_recipients(to="new@site.com")
        form.save(update_fields=["recipients"])
        record_recipient_change(
            form,
            old_recipients=build_recipients(to="old@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        )
        form.recipients = build_recipients(to="third@site.com")
        form.save(update_fields=["recipients"])
        assert record_recipient_change(
            form,
            old_recipients=build_recipients(to="new@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        ) is not None
        assert SiteEvent.objects.count() == 2

    def test_an_expired_cooldown_lets_the_same_transition_through(self, form):
        from datetime import timedelta

        kwargs = dict(
            old_recipients=build_recipients(to="old@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        )
        form.recipients = build_recipients(to="new@site.com")
        form.save(update_fields=["recipients"])
        first = record_recipient_change(form, **kwargs)
        SiteEvent.objects.filter(pk=first.pk).update(
            occurred_at=timezone.now() - timedelta(days=30)
        )
        assert record_recipient_change(form, **kwargs) is not None
