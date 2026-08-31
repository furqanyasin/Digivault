"""Reading form recipients from a site's own WordPress REST API.

Covers the shared scaffold: how the credential becomes an Authorization header,
what counts as "no answer", and the precedence rule that keeps this weaker
source from displacing WP Connect.
"""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.common.outbound import FetchResult
from apps.credentials.models import Credential
from apps.credentials.wp_access import resolve_wp_credential
from apps.scripts.models import DetectedForm
from apps.websites import wp_api_forms
from apps.websites.models import Website
from apps.websites.wp_forms import apply_recipients

PAGE = "https://wpapi.test/contact"


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="wpapi_o@test.com", password="Pass123!")
    return TeamService.create(name="WP API Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="WP API Site", domain="wpapi.test")


def _wp_credential(team, website, password="app pass"):
    cred = Credential(
        team=team,
        website=website,
        label="wp",
        credential_type=Credential.CredentialType.WORDPRESS_APP_PASSWORD,
    )
    cred.set_username("admin")
    cred.set_password(password)
    cred.save()
    return cred


def test_basic_auth_header_is_standard_basic(team, website):
    _wp_credential(team, website)

    header = wp_api_forms.basic_auth_header(resolve_wp_credential(website))

    # base64("admin:app pass")
    assert header == {"Authorization": "Basic YWRtaW46YXBwIHBhc3M="}


def test_site_base_url_adds_a_scheme(website):
    assert wp_api_forms.site_base_url(website) == "https://wpapi.test"


def test_apply_recipients_writes_the_source_it_is_given(website):
    form = DetectedForm.objects.create(
        website=website, page_url=PAGE, fingerprint="f1", form_name="Contact"
    )

    written = apply_recipients(
        website,
        [{"name": "Contact", "to": "leads@example.com"}],
        source=DetectedForm.RecipientSource.WP_API,
    )

    form.refresh_from_db()
    assert written == 1
    assert form.recipient_source == DetectedForm.RecipientSource.WP_API
    assert form.recipients["to"] == ["leads@example.com"]


def test_apply_recipients_still_defaults_to_wp_connect(website):
    """The existing caller passes no source and must be unaffected."""
    form = DetectedForm.objects.create(
        website=website, page_url=PAGE, fingerprint="f1", form_name="Contact"
    )

    apply_recipients(website, [{"name": "Contact", "to": "leads@example.com"}])

    form.refresh_from_db()
    assert form.recipient_source == DetectedForm.RecipientSource.WORDPRESS


def test_a_wp_api_answer_never_overwrites_a_wp_connect_answer(website):
    form = DetectedForm.objects.create(
        website=website,
        page_url=PAGE,
        fingerprint="f1",
        form_name="Contact",
        recipients={"to": ["truth@example.com"], "cc": [], "bcc": []},
        recipient_source=DetectedForm.RecipientSource.WORDPRESS,
    )

    apply_recipients(
        website,
        [{"name": "Contact", "to": "stale@example.com"}],
        source=DetectedForm.RecipientSource.WP_API,
    )

    form.refresh_from_db()
    assert form.recipients["to"] == ["truth@example.com"]
    assert form.recipient_source == DetectedForm.RecipientSource.WORDPRESS


def test_a_wp_connect_answer_does_overwrite_a_wp_api_one(website):
    form = DetectedForm.objects.create(
        website=website,
        page_url=PAGE,
        fingerprint="f1",
        form_name="Contact",
        recipients={"to": ["guess@example.com"], "cc": [], "bcc": []},
        recipient_source=DetectedForm.RecipientSource.WP_API,
    )

    apply_recipients(website, [{"name": "Contact", "to": "truth@example.com"}])

    form.refresh_from_db()
    assert form.recipients["to"] == ["truth@example.com"]
    assert form.recipient_source == DetectedForm.RecipientSource.WORDPRESS


def test_sync_website_is_a_no_op_without_a_credential(website):
    assert wp_api_forms.sync_website(website) == 0


def _stub_fetch(monkeypatch, **kwargs):
    monkeypatch.setattr(
        wp_api_forms.outbound,
        "fetch",
        lambda *a, **kw: FetchResult(
            headers={}, elapsed_ms=1, final_url="https://wpapi.test/", **kwargs
        ),
    )


def test_fetch_json_treats_a_truncated_body_as_no_answer(team, website, monkeypatch):
    _wp_credential(team, website)
    _stub_fetch(monkeypatch, status_code=200, body='[{"id":1', truncated=True)

    parsed, status = wp_api_forms.fetch_json(
        website, "wp/v2/pages", resolve_wp_credential(website)
    )

    assert parsed is None
    assert status == 200


def test_fetch_json_reports_the_status_on_a_rejection(team, website, monkeypatch):
    _wp_credential(team, website)
    _stub_fetch(monkeypatch, status_code=401, body="")

    parsed, status = wp_api_forms.fetch_json(
        website, "wp/v2/pages", resolve_wp_credential(website)
    )

    assert parsed is None
    assert status == 401


def test_fetch_json_parses_a_good_answer(team, website, monkeypatch):
    _wp_credential(team, website)
    _stub_fetch(monkeypatch, status_code=200, body='[{"id": 7}]')

    parsed, status = wp_api_forms.fetch_json(
        website, "wp/v2/pages", resolve_wp_credential(website)
    )

    assert parsed == [{"id": 7}]
    assert status == 200


def test_fetch_json_reports_zero_when_the_request_never_left(team, website, monkeypatch):
    from apps.common.ssrf import BlockedURLError

    _wp_credential(team, website)

    def _blocked(*a, **kw):
        raise BlockedURLError("private address")

    monkeypatch.setattr(wp_api_forms.outbound, "fetch", _blocked)

    parsed, status = wp_api_forms.fetch_json(
        website, "wp/v2/pages", resolve_wp_credential(website)
    )

    assert parsed is None
    assert status == 0
