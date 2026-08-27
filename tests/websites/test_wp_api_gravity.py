"""Reading Gravity Forms notification recipients over its own REST API.

Gravity is the one plugin here that does not live in `wp_posts`, so it needs its
own reader — and the one whose notifications can point at a form field rather
than a literal address, which must not be recorded as an email.
"""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
from apps.websites import wp_api_forms
from apps.websites.models import Website
from apps.websites.wp_forms import apply_recipients


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="gf_o@test.com", password="Pass123!")
    return TeamService.create(name="Gravity Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Gravity Site", domain="gravity.test")


def _api(listing, details):
    def _fetch(site, path, credential, **kwargs):
        if path == "gf/v2/forms":
            return listing, 200
        for form_id, detail in details.items():
            if path == f"gf/v2/forms/{form_id}":
                return detail, 200
        return None, 404

    return _fetch


def test_reads_a_literal_notification_address(website):
    fetch = _api(
        {"1": {"id": "1", "title": "Contact"}},
        {"1": {"id": "1", "notifications": {
            "n1": {"to": "leads@example.com", "toType": "email"}
        }}},
    )

    entries = wp_api_forms.read_gravity(website, credential=object(), fetch=fetch)

    assert entries == [{
        "plugin": "gravityforms",
        "id_prefix": "gform_1",
        "to": "leads@example.com",
        "cc": "",
        "bcc": "",
    }]


def test_cc_and_bcc_are_carried_through(website):
    fetch = _api(
        {"2": {"id": "2"}},
        {"2": {"notifications": {"n1": {
            "to": "a@example.com", "toType": "email",
            "cc": "b@example.com", "bcc": "c@example.com",
        }}}},
    )

    entries = wp_api_forms.read_gravity(website, credential=object(), fetch=fetch)

    assert entries[0]["cc"] == "b@example.com"
    assert entries[0]["bcc"] == "c@example.com"


def test_a_field_routed_notification_is_skipped(website):
    """toType "field" resolves per submission — there is no fixed recipient, and
    the raw value is a field id that would display as a nonsense address."""
    fetch = _api(
        {"1": {"id": "1"}},
        {"1": {"notifications": {"n1": {"to": "3", "toType": "field"}}}},
    )

    assert wp_api_forms.read_gravity(website, credential=object(), fetch=fetch) == []


def test_a_routing_notification_is_skipped(website):
    fetch = _api(
        {"1": {"id": "1"}},
        {"1": {"notifications": {"n1": {"to": "", "toType": "routing"}}}},
    )

    assert wp_api_forms.read_gravity(website, credential=object(), fetch=fetch) == []


def test_notifications_as_a_list_are_accepted(website):
    fetch = _api(
        {"1": {"id": "1"}},
        {"1": {"notifications": [{"to": "l@example.com", "toType": "email"}]}},
    )

    entries = wp_api_forms.read_gravity(website, credential=object(), fetch=fetch)

    assert entries[0]["to"] == "l@example.com"


def test_gravity_not_installed_yields_nothing(website):
    assert wp_api_forms.read_gravity(
        website, credential=object(), fetch=lambda *a, **kw: (None, 404)
    ) == []


def test_gform_1_does_not_claim_gform_12(website):
    """The prefix rule lives in _match, but this reader is what produces the
    prefix, so pin the pairing end to end."""
    twelve = DetectedForm.objects.create(
        website=website, page_url="https://gravity.test/q",
        fingerprint="f12", form_id="gform_12",
    )
    one = DetectedForm.objects.create(
        website=website, page_url="https://gravity.test/c",
        fingerprint="f1", form_id="gform_1",
    )

    apply_recipients(
        website,
        [{"plugin": "gravityforms", "id_prefix": "gform_1", "to": "one@example.com"}],
        source=DetectedForm.RecipientSource.WP_API,
    )

    one.refresh_from_db()
    twelve.refresh_from_db()
    assert one.recipients["to"] == ["one@example.com"]
    assert twelve.recipients.get("to", []) == []
