"""A recipient read from the site's own API outranks the page markup.

The markup reads nothing on the plugins that matter, so without these guards a
pageview would clear an API-sourced address seconds after the sweep wrote it —
the same bug the WP Connect guard was added to fix.
"""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
from apps.scripts.tasks import _apply_page_recipients
from apps.websites.models import Website

PAGE = "https://precedence.test/contact"


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="prec_o@test.com", password="Pass123!")
    team = TeamService.create(name="Precedence Agency", owner=owner)
    return Website.objects.create(
        team=team, name="Precedence Site", domain="precedence.test"
    )


def _form(website, **kwargs):
    return DetectedForm.objects.create(
        website=website, page_url=PAGE, fingerprint="abc123", **kwargs
    )


def test_pageview_does_not_clear_a_wp_api_recipient(website):
    """An empty markup reading is not evidence the configured address is gone."""
    form = _form(
        website,
        recipients={"to": ["leads@example.com"], "cc": [], "bcc": []},
        recipient_source=DetectedForm.RecipientSource.WP_API,
    )

    _apply_page_recipients(form, {"recipients": {"to": "", "cc": "", "bcc": ""}})

    form.refresh_from_db()
    assert form.recipients["to"] == ["leads@example.com"]
    assert form.recipient_source == DetectedForm.RecipientSource.WP_API


def test_pageview_does_not_override_wp_api_with_a_markup_address(website):
    """Even a non-empty markup reading loses to the site's own configuration."""
    form = _form(
        website,
        recipients={"to": ["leads@example.com"], "cc": [], "bcc": []},
        recipient_source=DetectedForm.RecipientSource.WP_API,
    )

    _apply_page_recipients(form, {"recipients": {"to": "spam@example.com"}})

    form.refresh_from_db()
    assert form.recipients["to"] == ["leads@example.com"]
    assert form.recipient_source == DetectedForm.RecipientSource.WP_API


def test_a_page_recipient_is_still_written_when_nothing_stronger_exists(website):
    """The guard must not turn into "never write from the page"."""
    form = _form(website)

    _apply_page_recipients(form, {"recipients": {"to": "hello@example.com"}})

    form.refresh_from_db()
    assert form.recipients["to"] == ["hello@example.com"]
    assert form.recipient_source == DetectedForm.RecipientSource.PAGE
