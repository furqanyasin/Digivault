"""SEO regressions reach the team channel — but only with a stable subject key.

Without a key, every distinct alert body would open its own ClickUp task, so an
omitted key skips the chat post instead of creating churn.
"""
from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.site_health.notifications import notify_team
from apps.websites.models import Website


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="seoowner@x.io", password="Pass123!")
    team = TeamService.create(name="SEO Co", owner=owner)
    team.clickup_chat_url = "https://app.clickup.com/9001/chat/r/chan-77"
    team.clickup_api_token = "pk_test"
    team.save()
    return Website.objects.create(team=team, name="Example", domain="example.com")


def test_a_keyed_alert_announces_in_the_team_channel(website):
    with patch("apps.integrations.chat.notify_problem") as np:
        notify_team(website, "[Digivault] noindex", "body", subject_key="sitehealth:1:seo_noindex")

    assert np.called
    assert np.call_args.kwargs["subject"] == "sitehealth:1:seo_noindex"
    # The email framing prefix is stripped for the channel.
    assert np.call_args.kwargs["title"] == "noindex"


def test_an_unkeyed_alert_skips_the_chat_post(website):
    with patch("apps.integrations.chat.notify_problem") as np:
        notify_team(website, "[Digivault] something", "body")

    assert not np.called


def test_a_chat_failure_does_not_raise(website):
    with patch("apps.integrations.chat.notify_problem", side_effect=RuntimeError("boom")):
        notify_team(website, "s", "b", subject_key="sitehealth:1:x")


def test_the_seo_check_passes_a_key_built_from_the_event_type(website):
    """The event type is the stable part of the issue; the summary text is not."""
    import inspect

    from apps.site_health import tasks

    source = inspect.getsource(tasks.run_seo_check)
    # Both notify_team calls in run_seo_check must carry a subject_key, or their
    # alerts would silently never reach the team channel.
    assert source.count("notify_team(") == source.count("subject_key=")
    assert source.count("subject_key=") == 2
    assert "sitehealth:{website.id}:{event_type}" in source
