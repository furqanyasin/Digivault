"""Reading form recipients from a WordPress site's Stacks Monitor Connect snippet.

Covers the join between what WordPress reports and the rows the tracking snippet
created, and the precedence rule that keeps a page ingest from wiping it.
"""

import base64
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.credentials.models import Credential
import json as _json
import urllib.error

from apps.common import outbound
from apps.common.ssrf import BlockedURLError, assert_public_url
from apps.scripts.models import DetectedForm
from apps.scripts.tasks import _upsert_form
from apps.websites.models import Website
from apps.websites.wp_forms import (
    apply_recipients,
    build_signed_url,
    fetch_recipients,
    sync_website,
)

PAGE = "https://wpforms.test/contact"


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="wpf_o@test.com", password="Pass123!")
    team = TeamService.create(name="WP Forms Agency", owner=owner)
    return Website.objects.create(
        team=team,
        name="WP Site",
        domain="wpforms.test",
        wp_sso_secret="s3cr3t-for-tests",
    )


def _elementor_form(website, name="New Form"):
    _upsert_form(website, PAGE, {
        "form_id": "", "form_name": name, "form_action": PAGE,
        "detection_type": "native", "fields": [{"name": "email", "type": "email"}],
    })
    return DetectedForm.objects.get(website=website, form_name=name)


def _Resp(status_code=200, payload=None, text=""):
    """A response from the shared outbound client.

    wp_forms fetches through `apps.common.outbound` rather than `requests`, so
    it shares the platform's per-host budget and gets the SSRF guard re-applied
    on every redirect hop.
    """
    body = _json.dumps(payload) if payload is not None else text
    return outbound.FetchResult(
        status_code=status_code, body=body, headers={},
        elapsed_ms=1, final_url="https://example.test/",
    )


@pytest.mark.django_db
class TestSignedUrl:
    def test_signature_verifies_against_the_shared_secret(self, website):
        url = build_signed_url(website)
        assert url.startswith("https://wpforms.test/wp-json/stacksmonitor/v1/forms?p=")

        query = url.split("?", 1)[1]
        params = dict(p.split("=", 1) for p in query.split("&"))
        expected = hmac.new(
            website.wp_sso_secret.encode(), params["p"].encode(), hashlib.sha256
        ).hexdigest()
        assert params["s"] == expected

    def test_payload_carries_an_expiry_the_snippet_can_check(self, website):
        payload_b64 = build_signed_url(website).split("p=", 1)[1].split("&")[0]
        raw = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(raw))
        assert payload["exp"] > 0
        assert payload["jti"]


@pytest.mark.django_db
class TestApplyRecipients:
    def test_elementor_form_matched_by_name(self, website):
        form = _elementor_form(website, "New Form")
        written = apply_recipients(website, [{
            "plugin": "elementor", "name": "New Form", "id_prefix": "",
            "recipients": ["website@acme-agency.com"],
        }])
        form.refresh_from_db()
        assert written == 1
        assert form.recipients["to"] == ["website@acme-agency.com"]
        assert form.recipient_source == DetectedForm.RecipientSource.WORDPRESS

    def test_name_match_ignores_case_and_padding(self, website):
        form = _elementor_form(website, "New Form")
        apply_recipients(website, [{
            "name": "  new form  ", "recipients": ["a@b.com"],
        }])
        form.refresh_from_db()
        assert form.recipients["to"] == ["a@b.com"]

    def test_cf7_form_matched_by_id_prefix(self, website):
        _upsert_form(website, PAGE, {
            "form_id": "wpcf7-f12-p340-o1", "form_name": "",
            "detection_type": "native", "fields": [{"name": "your-email"}],
        })
        written = apply_recipients(website, [{
            "plugin": "contact-form-7", "name": "Contact form 1",
            "id_prefix": "wpcf7-f12-", "recipients": ["leads@site.com"],
        }])
        assert written == 1
        form = DetectedForm.objects.get(website=website, form_id="wpcf7-f12-p340-o1")
        assert form.recipients["to"] == ["leads@site.com"]

    def test_form_1_does_not_claim_form_12s_row(self, website):
        """`gform_1` is a prefix of `gform_12` — the id number must not run on."""
        _upsert_form(website, PAGE, {
            "form_id": "gform_12", "detection_type": "native",
            "fields": [{"name": "input_1"}],
        })
        written = apply_recipients(website, [{
            "plugin": "gravity-forms", "name": "", "id_prefix": "gform_1",
            "recipients": ["wrong@site.com"],
        }])
        assert written == 0
        assert DetectedForm.objects.get(form_id="gform_12").recipients == {
            "to": [], "cc": [], "bcc": [],
        }

    def test_wpforms_exact_id_still_matches(self, website):
        _upsert_form(website, PAGE, {
            "form_id": "wpforms-form-30", "detection_type": "native",
            "fields": [{"name": "wpforms[fields][0]"}],
        })
        assert apply_recipients(website, [{
            "id_prefix": "wpforms-form-30", "recipients": ["team@site.com"],
        }]) == 1

    def test_reported_form_with_no_detected_row_is_ignored(self, website):
        _elementor_form(website, "New Form")
        assert apply_recipients(website, [{
            "name": "Some Other Form", "recipients": ["x@y.com"],
        }]) == 0

    def test_every_recipient_is_stored_not_just_the_first(self, website):
        form = _elementor_form(website)
        apply_recipients(website, [{
            "name": "New Form", "recipients": ["first@site.com", "second@site.com"],
        }])
        form.refresh_from_db()
        assert form.recipients["to"] == ["first@site.com", "second@site.com"]

    def test_malformed_recipients_are_skipped(self, website):
        form = _elementor_form(website)
        for entry in ({"name": "New Form", "recipients": []},
                      {"name": "New Form", "recipients": ["not-an-email"]},
                      {"name": "New Form", "recipients": None},
                      {"name": "New Form"}):
            assert apply_recipients(website, [entry]) == 0
        form.refresh_from_db()
        assert form.recipients == {"to": [], "cc": [], "bcc": []}

    def test_a_second_identical_report_writes_nothing(self, website):
        _elementor_form(website)
        entry = {"name": "New Form", "recipients": ["website@acme-agency.com"]}
        assert apply_recipients(website, [entry]) == 1
        assert apply_recipients(website, [entry]) == 0


@pytest.mark.django_db
class TestPrecedence:
    def test_page_ingest_does_not_wipe_a_wordpress_recipient(self, website):
        """The whole point of the source field.

        An Elementor form's recipient is invisible in the markup, so every
        pageview re-reports it as "" — which used to overwrite what WordPress
        told us, on the very next page load.
        """
        form = _elementor_form(website)
        apply_recipients(website, [{
            "name": "New Form", "recipients": ["website@acme-agency.com"],
        }])

        _upsert_form(website, PAGE, {
            "form_id": "", "form_name": "New Form", "form_action": PAGE,
            "detection_type": "native", "recipient_email": "",
            "fields": [{"name": "email", "type": "email"}],
        })

        form.refresh_from_db()
        assert form.recipients["to"] == ["website@acme-agency.com"]
        assert form.recipient_source == DetectedForm.RecipientSource.WORDPRESS

    def test_wordpress_outranks_an_address_read_from_the_page(self, website):
        _upsert_form(website, PAGE, {
            "form_id": "", "form_name": "New Form", "form_action": PAGE,
            "detection_type": "native", "recipient_email": "old@site.com",
            "fields": [{"name": "email", "type": "email"}],
        })
        form = DetectedForm.objects.get(website=website, form_name="New Form")
        assert form.recipient_source == DetectedForm.RecipientSource.PAGE

        apply_recipients(website, [{
            "name": "New Form", "recipients": ["real@site.com"],
        }])
        form.refresh_from_db()
        assert form.recipients["to"] == ["real@site.com"]
        assert form.recipient_source == DetectedForm.RecipientSource.WORDPRESS

        # And a later pageview still can't take it back.
        _upsert_form(website, PAGE, {
            "form_id": "", "form_name": "New Form", "form_action": PAGE,
            "detection_type": "native", "recipient_email": "old@site.com",
            "fields": [{"name": "email", "type": "email"}],
        })
        form.refresh_from_db()
        assert form.recipients["to"] == ["real@site.com"]

    def test_a_page_recipient_still_fills_a_blank_row(self, website):
        _upsert_form(website, PAGE, {
            "form_id": "mailto-form", "detection_type": "native",
            "recipient_email": "Info@Site.com", "fields": [{"name": "email"}],
        })
        form = DetectedForm.objects.get(website=website, form_id="mailto-form")
        assert form.recipients["to"] == ["info@site.com"]  # normalized
        assert form.recipient_source == DetectedForm.RecipientSource.PAGE

    def test_an_empty_reading_does_not_clear_a_page_recipient(self, website):
        """One observation missing a mailto: is not proof the mailto: is gone."""
        payload = {
            "form_id": "mailto-form", "detection_type": "native",
            "recipient_email": "info@site.com", "fields": [{"name": "email"}],
        }
        _upsert_form(website, PAGE, payload)
        _upsert_form(website, PAGE, {**payload, "recipient_email": ""})
        form = DetectedForm.objects.get(website=website, form_id="mailto-form")
        assert form.recipients["to"] == ["info@site.com"]


@pytest.fixture
def reachable():
    """Let the fetch past the SSRF guard.

    `assert_public_url` resolves the host, so without this the test domain is
    rejected before any request is attempted and every response-handling test
    below passes for the wrong reason. The guard itself is covered separately,
    against its own exception rather than against real DNS.
    """
    with patch("apps.common.outbound.assert_public_url", return_value=None):
        yield


@pytest.mark.django_db
@pytest.mark.usefixtures("reachable")
class TestFetch:
    def test_site_without_a_secret_is_not_contacted(self, website):
        website.wp_sso_secret = ""
        with patch("apps.websites.wp_forms.outbound.fetch") as get:
            assert fetch_recipients(website) == []
        get.assert_not_called()

    @pytest.mark.parametrize("resp", [
        _Resp(status_code=404),
        _Resp(status_code=403),
        _Resp(status_code=200, payload=None, text="<html>"),
        _Resp(status_code=200, payload={"forms": "not-a-list"}),
        _Resp(status_code=200, payload=["bare", "list"]),
    ])
    def test_a_site_that_cannot_answer_is_not_an_error(self, website, resp):
        """Most sites have never pasted the snippet. That is a normal state."""
        with patch("apps.websites.wp_forms.outbound.fetch", return_value=resp):
            assert fetch_recipients(website) == []

    def test_a_timeout_is_swallowed(self, website):
        with patch(
            "apps.websites.wp_forms.outbound.fetch",
            side_effect=urllib.error.URLError("too slow"),
        ):
            assert fetch_recipients(website) == []

    def test_non_dict_entries_are_dropped(self, website):
        resp = _Resp(payload={"forms": [{"name": "ok", "recipients": ["a@b.com"]}, "junk", 7]})
        with patch("apps.websites.wp_forms.outbound.fetch", return_value=resp):
            assert fetch_recipients(website) == [
                {"name": "ok", "recipients": ["a@b.com"]}
            ]

    def test_sync_website_joins_a_live_response_onto_a_row(self, website):
        form = _elementor_form(website)
        resp = _Resp(payload={"forms": [{
            "plugin": "elementor", "name": "New Form", "id_prefix": "",
            "recipients": ["website@acme-agency.com"],
        }]})
        with patch("apps.websites.wp_forms.outbound.fetch", return_value=resp):
            assert sync_website(website) == 1
        form.refresh_from_db()
        assert form.recipients["to"] == ["website@acme-agency.com"]


@pytest.mark.django_db
class TestSsrfGuard:
    def test_a_blocked_host_is_never_requested(self, website):
        """A site pointed at localhost or a private range must not be fetched."""
        with patch(
            "apps.common.outbound.assert_public_url",
            side_effect=BlockedURLError("private address"),
        ), patch("apps.common.outbound._opener") as opener:
            assert fetch_recipients(website) == []
        opener.assert_not_called()

    def test_the_guard_rejects_a_loopback_domain(self, website):
        """The guard is real, not just called — asserted against it directly."""
        website.domain = "127.0.0.1"
        with pytest.raises(BlockedURLError):
            assert_public_url(build_signed_url(website))


@pytest.mark.django_db
class TestEndpoint:
    """The on-demand sync, so pasting the snippet and seeing the Forms tab fill
    in are the same minute rather than a day apart."""

    @pytest.fixture
    def client_for(self):
        from rest_framework.test import APIClient

        def _make(website):
            user = website.team.owner
            user.active_team = website.team
            user.save(update_fields=["active_team"])
            client = APIClient()
            client.force_authenticate(user=user)
            return client

        return _make

    @staticmethod
    def _url(website):
        return f"/api/v1/websites/{website.pk}/sync-form-recipients/"

    def test_requires_wordpress_api_credentials(self, client_for, website):
        website.wp_sso_secret = ""
        website.save(update_fields=["wp_sso_secret"])
        resp = client_for(website).post(self._url(website))
        assert resp.status_code == 409

    def test_reports_how_many_rows_it_filled(self, client_for, website, reachable, monkeypatch):
        form = _elementor_form(website)
        credential = Credential(
            team=website.team,
            website=website,
            label="WordPress API",
            credential_type=Credential.CredentialType.WORDPRESS_APP_PASSWORD,
        )
        credential.set_username("api-user")
        credential.set_password("app-password")
        credential.save()
        monkeypatch.setattr(
            "apps.websites.wp_api_forms.sync_website_detailed",
            lambda site: {
                "updated": 1,
                "source": "wp_api",
                "reason": "completed",
            },
        )
        resp = client_for(website).post(self._url(website))
        assert resp.status_code == 200
        assert resp.data["updated"] == 1
        assert resp.data["source"] == "wp_api"

    def test_a_site_that_cannot_answer_reports_zero(self, client_for, website, reachable, monkeypatch):
        _elementor_form(website)
        credential = Credential(
            team=website.team,
            website=website,
            label="WordPress API",
            credential_type=Credential.CredentialType.WORDPRESS_APP_PASSWORD,
        )
        credential.set_username("api-user")
        credential.set_password("app-password")
        credential.save()
        monkeypatch.setattr(
            "apps.websites.wp_api_forms.sync_website_detailed",
            lambda site: {
                "updated": 0,
                "source": "wp_api",
                "reason": "unsupported_plugin",
            },
        )
        resp = client_for(website).post(self._url(website))
        assert resp.status_code == 200
        assert resp.data["updated"] == 0
        assert resp.data["reason"] == "unsupported_plugin"


@pytest.mark.django_db
class TestReportedCopies:
    def test_cc_and_bcc_are_stored(self, website):
        form = _elementor_form(website)
        apply_recipients(website, [{
            "plugin": "elementor", "name": "New Form",
            "to": ["website@acme-agency.com"],
            "cc": ["manager@acme-agency.com"],
            "bcc": ["archive@acme-agency.com"],
        }])
        form.refresh_from_db()
        assert form.recipients == {
            "to": ["website@acme-agency.com"],
            "cc": ["manager@acme-agency.com"],
            "bcc": ["archive@acme-agency.com"],
        }

    def test_every_to_address_is_stored_not_just_the_first(self, website):
        form = _elementor_form(website)
        apply_recipients(website, [{
            "name": "New Form", "to": ["first@site.com", "second@site.com"],
        }])
        form.refresh_from_db()
        assert form.recipients["to"] == ["first@site.com", "second@site.com"]

    def test_the_old_recipients_key_is_still_accepted(self, website):
        """A site pasted with the previous snippet answers with `recipients`."""
        form = _elementor_form(website)
        assert apply_recipients(website, [{
            "name": "New Form", "recipients": ["website@acme-agency.com"],
        }]) == 1
        form.refresh_from_db()
        assert form.recipients["to"] == ["website@acme-agency.com"]

    def test_a_reordered_report_is_not_a_write(self, website):
        _elementor_form(website)
        first = {"name": "New Form", "to": ["a@site.com", "b@site.com"]}
        assert apply_recipients(website, [first]) == 1
        assert apply_recipients(
            website, [{"name": "New Form", "to": ["b@site.com", "a@site.com"]}]
        ) == 0
