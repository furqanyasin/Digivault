"""Multi-type form detection — native, div-based, and embedded forms."""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
from apps.scripts.tasks import _upsert_form
from apps.websites.models import Website


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="forms_o@test.com", password="Pass123!")
    team = TeamService.create(name="Forms Agency", owner=owner)
    return Website.objects.create(team=team, name="Forms Site", domain="forms.io")


PAGE = "https://forms.io/contact"


@pytest.mark.django_db
class TestUpsertForm:
    def test_native_form_stored_with_fields(self, website):
        _upsert_form(website, PAGE, {
            "form_id": "cf7", "form_name": "contact", "form_action": "/submit",
            "form_method": "POST", "detection_type": "native", "provider": "",
            "fields": [{"name": "email", "type": "email", "label": "Email", "required": True}],
        })
        form = DetectedForm.objects.get(website=website, page_url=PAGE)
        assert form.detection_type == "native"
        assert form.form_method == "post"  # normalised to lowercase
        assert len(form.fields) == 1

    def test_two_div_forms_with_empty_action_coexist(self, website):
        """Both div forms have an empty action — distinct fingerprints keep them apart."""
        _upsert_form(website, PAGE, {
            "detection_type": "dom", "form_action": "",
            "fields": [{"name": "name"}, {"name": "phone"}],
        })
        _upsert_form(website, PAGE, {
            "detection_type": "dom", "form_action": "",
            "fields": [{"name": "email"}, {"name": "message"}],
        })
        assert DetectedForm.objects.filter(website=website, page_url=PAGE).count() == 2

    def test_embedded_form_stores_provider_and_no_fields(self, website):
        _upsert_form(website, PAGE, {
            "detection_type": "embedded", "provider": "HubSpot",
            "form_action": "https://hsforms.net/embed/123", "fields": [],
        })
        form = DetectedForm.objects.get(website=website, page_url=PAGE)
        assert form.detection_type == "embedded"
        assert form.provider == "HubSpot"
        assert form.fields == []

    def test_reingest_same_form_updates_in_place(self, website):
        payload = {
            "detection_type": "dom", "form_action": "",
            "fields": [{"name": "email"}, {"name": "message"}],
        }
        _upsert_form(website, PAGE, payload)
        _upsert_form(website, PAGE, payload)
        assert DetectedForm.objects.filter(website=website, page_url=PAGE).count() == 1

    def test_recipient_email_is_normalized_on_store(self, website):
        _upsert_form(website, PAGE, {
            "detection_type": "native", "form_action": "mailto:Info@Example.com",
            "fields": [{"name": "name"}], "recipient_email": " Info@Example.com ",
        })
        form = DetectedForm.objects.get(website=website, page_url=PAGE)
        assert form.recipients["to"] == ["info@example.com"]

    def test_invalid_recipient_email_does_not_400(self, website):
        _upsert_form(website, PAGE, {
            "detection_type": "native", "form_action": "/submit",
            "fields": [{"name": "name"}], "recipient_email": "not-an-email",
        })
        form = DetectedForm.objects.get(website=website, page_url=PAGE)
        assert form.recipients == {"to": [], "cc": [], "bcc": []}

    def test_recipient_email_update_is_idempotent_across_ingests(self, website):
        payload = {
            "detection_type": "native", "form_action": "/submit",
            "fields": [{"name": "name"}], "recipient_email": "info@example.com",
        }
        _upsert_form(website, PAGE, payload)
        _upsert_form(website, PAGE, payload)
        assert DetectedForm.objects.filter(website=website, page_url=PAGE).count() == 1
        form = DetectedForm.objects.get(website=website, page_url=PAGE)
        assert form.recipients["to"] == ["info@example.com"]


@pytest.mark.django_db
class TestIngestFormsEndToEnd:
    def test_ingest_persists_all_three_types(self, website):
        from rest_framework.test import APIClient

        client = APIClient()
        payload = {
            "site_id": website.site_id,
            "page_url": PAGE,
            "scripts": [],
            "forms": [
                {"detection_type": "native", "form_action": "/a",
                 "fields": [{"name": "email", "type": "email"}]},
                {"detection_type": "dom", "form_action": "",
                 "fields": [{"name": "name"}, {"name": "phone"}]},
                {"detection_type": "embedded", "provider": "Typeform",
                 "form_action": "https://typeform.com/to/x", "fields": []},
            ],
            "user_agent": "Mozilla/5.0",
            "snippet_version": "1.4",
        }
        resp = client.post("/api/ingest/", payload, format="json")
        assert resp.status_code == 202

        forms = DetectedForm.objects.filter(website=website, page_url=PAGE)
        assert forms.count() == 3
        assert set(forms.values_list("detection_type", flat=True)) == {"native", "dom", "embedded"}

    def test_ingest_stores_recipient_email(self, website):
        from rest_framework.test import APIClient

        client = APIClient()
        resp = client.post("/api/ingest/", {
            "site_id": website.site_id,
            "page_url": PAGE,
            "scripts": [],
            "forms": [{
                "detection_type": "native",
                "form_action": "mailto:info@example.com",
                "recipient_email": "Info@Example.com",
                "fields": [{"name": "email", "type": "email"}],
            }],
            "snippet_version": "1.11",
        }, format="json")
        assert resp.status_code == 202

        form = DetectedForm.objects.get(website=website, page_url=PAGE)
        assert form.recipients["to"] == ["info@example.com"]

    def test_ingest_rejects_overlong_recipient_email(self, website):
        from rest_framework.test import APIClient

        client = APIClient()
        resp = client.post("/api/ingest/", {
            "site_id": website.site_id,
            "page_url": PAGE,
            "scripts": [],
            "forms": [{
                "detection_type": "native",
                "form_action": "/submit",
                "recipient_email": f"a@{'x' * 300}.com",
                "fields": [{"name": "email", "type": "email"}],
            }],
            "snippet_version": "1.11",
        }, format="json")
        assert resp.status_code == 400


@pytest.mark.django_db
class TestRecipientLists:
    def test_a_comma_separated_to_stores_every_address(self, website):
        """The bug that started this: two addresses in one To stored nothing."""
        _upsert_form(website, PAGE, {
            "form_id": "multi", "detection_type": "native",
            "fields": [{"name": "email"}],
            "recipients": {"to": "sales@site.com, dev@site.com"},
        })
        form = DetectedForm.objects.get(website=website, form_id="multi")
        assert form.recipients["to"] == ["sales@site.com", "dev@site.com"]

    def test_cc_and_bcc_are_stored_separately(self, website):
        _upsert_form(website, PAGE, {
            "form_id": "copies", "detection_type": "native",
            "fields": [{"name": "email"}],
            "recipients": {
                "to": "lead@site.com", "cc": "manager@site.com",
                "bcc": "archive@site.com",
            },
        })
        form = DetectedForm.objects.get(website=website, form_id="copies")
        assert form.recipients == {
            "to": ["lead@site.com"], "cc": ["manager@site.com"],
            "bcc": ["archive@site.com"],
        }

    def test_a_legacy_recipient_email_payload_still_works(self, website):
        """The snippet is cached for 5 minutes and pasted copies live longer;
        a browser running yesterday's snippet must not lose its recipient."""
        _upsert_form(website, PAGE, {
            "form_id": "legacy", "detection_type": "native",
            "fields": [{"name": "email"}], "recipient_email": "Info@Site.com",
        })
        form = DetectedForm.objects.get(website=website, form_id="legacy")
        assert form.recipients["to"] == ["info@site.com"]

    def test_an_empty_reading_does_not_clear_stored_recipients(self, website):
        payload = {
            "form_id": "keep", "detection_type": "native",
            "fields": [{"name": "email"}],
            "recipients": {"to": "info@site.com"},
        }
        _upsert_form(website, PAGE, payload)
        _upsert_form(website, PAGE, {**payload, "recipients": {}})
        form = DetectedForm.objects.get(website=website, form_id="keep")
        assert form.recipients["to"] == ["info@site.com"]

    def test_a_junk_address_does_not_400_the_payload(self, website):
        _upsert_form(website, PAGE, {
            "form_id": "junk", "detection_type": "native",
            "fields": [{"name": "email"}],
            "recipients": {"to": "not-an-email"},
        })
        form = DetectedForm.objects.get(website=website, form_id="junk")
        assert form.recipients == {"to": [], "cc": [], "bcc": []}


class TestFingerprint:
    def test_field_order_does_not_change_fingerprint(self):
        a = DetectedForm.compute_fingerprint(
            {"detection_type": "dom", "fields": [{"name": "a"}, {"name": "b"}]}
        )
        b = DetectedForm.compute_fingerprint(
            {"detection_type": "dom", "fields": [{"name": "b"}, {"name": "a"}]}
        )
        assert a == b

    def test_different_fields_change_fingerprint(self):
        a = DetectedForm.compute_fingerprint(
            {"detection_type": "dom", "fields": [{"name": "a"}]}
        )
        b = DetectedForm.compute_fingerprint(
            {"detection_type": "dom", "fields": [{"name": "z"}]}
        )
        assert a != b
