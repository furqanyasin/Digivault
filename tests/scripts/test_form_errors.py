"""Form submission error detection — filtering, sanitisation, ingest, listing."""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.form_errors import (
    is_important_form_error,
    sanitize_error_message,
    sanitize_page_url,
)
from apps.scripts.models import FormSubmissionError
from apps.websites.models import Website


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="ferr_o@test.com", password="Pass123!")
    team = TeamService.create(name="FormErr Agency", owner=owner)
    return Website.objects.create(team=team, name="FormErr Site", domain="formerr.io")


class TestImportanceFilter:
    @pytest.mark.parametrize("msg", [
        "There was an error trying to send your message. Please try again later.",
        "Your submission failed because of a server error.",
        "Mail failed: SMTP connect() failed",
        "Request failed with status 503",
        "Internal error — could not be sent",
    ])
    def test_important_messages_pass(self, msg):
        assert is_important_form_error(msg) is True

    @pytest.mark.parametrize("msg", [
        "This field is required.",
        "Please fill in the required fields.",
        "Please enter a valid email address.",
        "The captcha was not solved correctly.",
        "",
    ])
    def test_validation_noise_rejected(self, msg):
        assert is_important_form_error(msg) is False


class TestSanitizers:
    def test_page_url_redacts_sensitive_params(self):
        url = "https://x.io/contact?page=2&email=a@b.com&token=abc123"
        out = sanitize_page_url(url)
        assert "a%40b.com" not in out and "a@b.com" not in out
        assert "abc123" not in out
        assert "page=2" in out

    def test_page_url_without_query_unchanged(self):
        assert sanitize_page_url("https://x.io/contact") == "https://x.io/contact"

    def test_message_redacts_email_password_digits(self):
        msg = "submission failed email=client@example.com password=secret123 ref 12345678901"
        out = sanitize_error_message(msg)
        assert "client@example.com" not in out
        assert "secret123" not in out
        assert "12345678901" not in out
        assert "[hidden]" in out


@pytest.mark.django_db
class TestFormErrorIngest:
    URL = "/api/ingest/form-errors/"

    def _payload(self, website, message, **kw):
        return {
            "site_id": website.site_id,
            "page_url": "https://formerr.io/contact",
            "source": kw.get("source", "Contact Form 7"),
            "form_id": kw.get("form_id", "wpcf7-123"),
            "message": message,
        }

    def test_important_error_is_stored_sanitized(self, api_client, website):
        msg = "Submission failed: server error. Contact admin@formerr.io"
        resp = api_client.post(self.URL, self._payload(website, msg), format="json")
        assert resp.status_code == 202
        err = FormSubmissionError.objects.get(website=website)
        assert err.source == "Contact Form 7"
        assert "admin@formerr.io" not in err.message
        assert "[hidden]" in err.message

    def test_validation_noise_not_stored(self, api_client, website):
        resp = api_client.post(
            self.URL, self._payload(website, "This field is required."), format="json"
        )
        assert resp.status_code == 202  # acknowledged, no signal to probers
        assert FormSubmissionError.objects.count() == 0

    def test_unknown_site_id_404(self, api_client, website):
        payload = self._payload(website, "server error")
        payload["site_id"] = "nonexistent-site-id"
        resp = api_client.post(self.URL, payload, format="json")
        assert resp.status_code == 404

    def test_domain_mismatch_403(self, api_client, website):
        resp = api_client.post(
            self.URL,
            self._payload(website, "submission failed — server error"),
            format="json",
            HTTP_ORIGIN="https://evil.example",
        )
        assert resp.status_code == 403
        assert FormSubmissionError.objects.count() == 0

    def test_team_scoped_listing(self, auth_client, team):
        site = Website.objects.create(team=team, name="Mine", domain="mine.io")
        FormSubmissionError.objects.create(
            website=site, source="WPForms", form_id="f1",
            page_url="https://mine.io/contact", message="server error",
        )
        resp = auth_client.get(f"/api/v1/websites/{site.pk}/form-errors/")
        assert resp.status_code == 200
        assert len(resp.data) == 1
        assert resp.data[0]["source"] == "WPForms"
