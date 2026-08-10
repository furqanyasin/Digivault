"""A stored form error alerts the team — shared ClickUp feed + configured channels.

Storing the row was never the point: a broken contact form is silent revenue
loss, and nobody watches the dashboard for it. These tests pin the delivery and,
just as importantly, the cooldown — every visitor who hits the broken form posts
another error, and one message per visitor is worse than none.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import NotificationChannel
from apps.scripts.models import FormSubmissionError
from apps.scripts.notifications import notify_form_error
from apps.websites.models import Website


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="fealert@test.com", password="Pass123!")
    team = TeamService.create(name="FormAlert Agency", owner=owner)
    team.clickup_chat_url = "https://app.clickup.com/9001/chat/r/chan-77"
    team.clickup_api_token = "pk_test"
    team.save()
    return Website.objects.create(team=team, name="Alert Site", domain="alertsite.io")


def _error(website, **kw):
    return FormSubmissionError.objects.create(
        website=website,
        source=kw.get("source", "Contact Form 7"),
        form_id=kw.get("form_id", "wpcf7-123"),
        page_url=kw.get("page_url", "https://alertsite.io/contact"),
        message=kw.get("message", "Submission failed: server error."),
        alerted_at=kw.get("alerted_at"),
    )


class TestTeamChannelAnnounce:
    def test_a_stored_error_announces_in_the_team_channel(self, website):
        err = _error(website)

        with patch("apps.integrations.chat.notify_problem") as np:
            notify_form_error(err)

        assert np.called
        kwargs = np.call_args.kwargs
        assert kwargs["subject"] == f"form:{website.id}:wpcf7-123"
        assert "form" in kwargs["title"].lower()
        rendered = dict(kwargs["fields"])
        assert rendered["Error"] == "Submission failed: server error."
        assert rendered["Page"] == "https://alertsite.io/contact"
        assert rendered["Form"] == "Contact Form 7 (wpcf7-123)"

    def test_alerting_stamps_the_row_that_raised_it(self, website):
        err = _error(website)

        with patch("apps.integrations.chat.notify_problem"):
            notify_form_error(err)

        err.refresh_from_db()
        assert err.alerted_at is not None

    def test_a_repeat_error_on_the_same_form_stays_quiet(self, website):
        _error(website, alerted_at=timezone.now())
        repeat = _error(website)

        with patch("apps.integrations.chat.notify_problem") as np:
            assert notify_form_error(repeat) is False

        assert not np.called
        repeat.refresh_from_db()
        assert repeat.alerted_at is None

    def test_a_different_form_on_the_same_site_still_announces(self, website):
        _error(website, form_id="wpcf7-123", alerted_at=timezone.now())
        other = _error(website, form_id="wpforms-9")

        with patch("apps.integrations.chat.notify_problem") as np:
            notify_form_error(other)

        assert np.called

    def test_a_form_that_keeps_failing_is_re_reported_after_the_cooldown(self, website):
        _error(website, alerted_at=timezone.now() - timedelta(hours=25))
        # Errors kept arriving in between — they must not extend the silence.
        _error(website)
        fresh = _error(website)

        with patch("apps.integrations.chat.notify_problem") as np:
            notify_form_error(fresh)

        assert np.called


@pytest.mark.django_db
class TestConfiguredChannels:
    def test_an_email_channel_receives_the_alert(self, website):
        NotificationChannel.objects.create(
            team=website.team, name="Ops", channel_type="email",
            config={"addresses": ["ops@agency.io"]},
        )
        err = _error(website)

        with patch("apps.integrations.chat.notify_problem"):
            notify_form_error(err)

        assert len(mail.outbox) == 1
        assert "alertsite.io" in mail.outbox[0].subject
        assert "https://alertsite.io/contact" in mail.outbox[0].body

    def test_a_clickup_channel_receives_the_alert(self, website):
        NotificationChannel.objects.create(
            team=website.team, name="Client board", channel_type="clickup",
            config={"api_token": "pk_x", "task_id": "task-1"},
        )
        err = _error(website)

        with patch("apps.scripts.notifications.post_clickup", return_value=True) as pc, \
             patch("apps.integrations.chat.notify_problem"):
            notify_form_error(err)

        assert pc.called
        assert "Submission failed: server error." in pc.call_args.args[1]

    def test_a_failing_channel_does_not_stop_the_others(self, website):
        NotificationChannel.objects.create(
            team=website.team, name="Broken", channel_type="clickup",
            config={"api_token": "pk_x", "task_id": "task-1"},
        )
        NotificationChannel.objects.create(
            team=website.team, name="Ops", channel_type="email",
            config={"addresses": ["ops@agency.io"]},
        )
        err = _error(website)

        with patch("apps.scripts.notifications.post_clickup", side_effect=RuntimeError("boom")), \
             patch("apps.integrations.chat.notify_problem"):
            notify_form_error(err)

        assert len(mail.outbox) == 1


@pytest.mark.django_db
class TestIngestWiring:
    URL = "/api/ingest/form-errors/"

    def _payload(self, website, message):
        return {
            "site_id": website.site_id,
            "page_url": "https://alertsite.io/contact",
            "source": "Contact Form 7",
            "form_id": "wpcf7-123",
            "message": message,
        }

    def test_ingesting_an_important_error_alerts_the_team(self, api_client, website):
        with patch("apps.integrations.chat.notify_problem") as np:
            resp = api_client.post(
                self.URL, self._payload(website, "Submission failed: server error."),
                format="json",
            )

        assert resp.status_code == 202
        assert np.called

    def test_validation_noise_alerts_nobody(self, api_client, website):
        with patch("apps.integrations.chat.notify_problem") as np:
            resp = api_client.post(
                self.URL, self._payload(website, "This field is required."), format="json"
            )

        assert resp.status_code == 202
        assert not np.called

    def test_a_delivery_failure_still_acknowledges_the_snippet(self, api_client, website):
        with patch(
            "apps.scripts.notifications.notify_form_error", side_effect=RuntimeError("boom")
        ):
            resp = api_client.post(
                self.URL, self._payload(website, "Submission failed: server error."),
                format="json",
            )

        assert resp.status_code == 202
        assert FormSubmissionError.objects.count() == 1
