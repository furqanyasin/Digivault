"""Phase 0.3 — ingest endpoint hardening (list-length + body-size caps)."""

import pytest
from unittest.mock import patch

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.serializers import MAX_FORMS_PER_PAYLOAD, MAX_SCRIPTS_PER_PAYLOAD
from apps.websites.models import Website


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="harden_o@test.com", password="Pass123!")
    team = TeamService.create(name="Harden Agency", owner=owner)
    return Website.objects.create(team=team, name="Harden Site", domain="harden.io")


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


def _script(i=0):
    return {
        "src": f"https://cdn.example.com/s{i}.js",
        "location": "head",
        "is_async": True,
        "is_defer": False,
        "is_inline": False,
        "inline_hash": "",
        "wp_plugin": "",
        "wp_post_id": None,
    }


def _payload(site_id, scripts):
    return {
        "site_id": site_id,
        "page_url": "https://harden.io/",
        "scripts": scripts,
        "user_agent": "Mozilla/5.0",
        "snippet_version": "1.0",
    }


@pytest.mark.django_db
class TestIngestCaps:
    def test_too_many_scripts_rejected_without_queuing(self, api_client, website):
        scripts = [_script(i) for i in range(MAX_SCRIPTS_PER_PAYLOAD + 1)]
        with patch("apps.scripts.views.process_ingest_payload.delay") as mock_task:
            resp = api_client.post(
                "/api/ingest/", _payload(website.site_id, scripts), format="json"
            )
        assert resp.status_code == 400
        mock_task.assert_not_called()

    def test_at_limit_scripts_accepted(self, api_client, website):
        scripts = [_script(i) for i in range(MAX_SCRIPTS_PER_PAYLOAD)]
        with patch("apps.scripts.views.process_ingest_payload.delay") as mock_task:
            resp = api_client.post(
                "/api/ingest/", _payload(website.site_id, scripts), format="json"
            )
        assert resp.status_code == 202
        mock_task.assert_called_once()

    def test_too_many_forms_rejected(self, api_client, website):
        payload = _payload(website.site_id, [_script()])
        payload["forms"] = [
            {"form_id": f"f{i}", "form_action": "/submit"}
            for i in range(MAX_FORMS_PER_PAYLOAD + 1)
        ]
        with patch("apps.scripts.views.process_ingest_payload.delay") as mock_task:
            resp = api_client.post("/api/ingest/", payload, format="json")
        assert resp.status_code == 400
        mock_task.assert_not_called()

    def test_oversized_body_rejected(self, website):
        # The test client recomputes CONTENT_LENGTH from the real body, so drive
        # the view directly with a forged oversized Content-Length.
        from rest_framework.test import APIRequestFactory

        from apps.scripts.views import IngestView

        factory = APIRequestFactory()
        request = factory.post(
            "/api/ingest/", _payload(website.site_id, [_script()]), format="json"
        )
        request.META["CONTENT_LENGTH"] = str(5 * 1024 * 1024)
        with patch("apps.scripts.views.process_ingest_payload.delay") as mock_task:
            resp = IngestView.as_view()(request)
        assert resp.status_code == 413
        mock_task.assert_not_called()
