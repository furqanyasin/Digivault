import pytest
from unittest.mock import patch

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="ingest_o@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Ingest Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Ingest Site", domain="ingest.io")


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()


@pytest.mark.django_db
class TestIngestEndpoint:
    def _payload(self, site_id, page_url="https://ingest.io/"):
        return {
            "site_id": site_id,
            "page_url": page_url,
            "scripts": [
                {
                    "src": "https://www.googletagmanager.com/gtm.js?id=GTM-TEST",
                    "location": "head",
                    "is_async": True,
                    "is_defer": False,
                    "is_inline": False,
                    "inline_hash": "",
                    "wp_plugin": "",
                    "wp_post_id": None,
                }
            ],
            "user_agent": "Mozilla/5.0",
            "snippet_version": "1.0",
        }

    def test_valid_payload_returns_202(self, api_client, website):
        with patch("apps.scripts.views.process_ingest_payload.delay") as mock_task:
            resp = api_client.post(
                "/api/ingest/",
                self._payload(website.site_id),
                format="json",
            )
        assert resp.status_code == 202
        mock_task.assert_called_once()

    def test_unknown_site_id_returns_404(self, api_client):
        resp = api_client.post(
            "/api/ingest/",
            self._payload("nonexistent-site-id-xyz"),
            format="json",
        )
        assert resp.status_code == 404

    def test_missing_page_url_returns_400(self, api_client, website):
        payload = self._payload(website.site_id)
        del payload["page_url"]
        resp = api_client.post("/api/ingest/", payload, format="json")
        assert resp.status_code == 400

    def test_no_auth_required(self, api_client, website):
        """Ingest must work without any Authorization header."""
        with patch("apps.scripts.views.process_ingest_payload.delay"):
            resp = api_client.post(
                "/api/ingest/",
                self._payload(website.site_id),
                format="json",
            )
        assert resp.status_code == 202


@pytest.mark.django_db
class TestIngestRecipientsIsLenient:
    """`recipients` used to be a nested `Serializer` field, which made it a
    *validated* key: `null`, a bare string, a `to` shaped as a list instead
    of a string, or an over-length value all 400d the whole payload and
    dropped the scripts posted alongside it. `build_recipients` in the
    upsert already rejects a junk address entry-by-entry — this is the same
    "lenient at the edge, validated in the upsert" precedent `recipient_email`
    on the same serializer already follows.
    """

    def _payload(self, site_id, recipients):
        return {
            "site_id": site_id,
            "page_url": "https://ingest.io/contact",
            "scripts": [
                {
                    "src": "https://www.googletagmanager.com/gtm.js?id=GTM-TEST",
                    "location": "head",
                    "is_async": True,
                    "is_defer": False,
                    "is_inline": False,
                    "inline_hash": "",
                    "wp_plugin": "",
                    "wp_post_id": None,
                }
            ],
            "forms": [{
                "form_id": "contact", "form_name": "Contact",
                "form_action": "", "form_method": "post",
                "detection_type": "native", "provider": "",
                "recipient_email": "", "recipients": recipients,
                "fields": [],
            }],
            "user_agent": "Mozilla/5.0",
            "snippet_version": "1.0",
        }

    @pytest.mark.parametrize("recipients", [
        None,
        "garbage",
        {"to": ["a@site.com", "b@site.com"]},
        {"to": "x" * 3000 + "@site.com"},
    ], ids=["null", "bare-string", "to-as-list", "overlong-to"])
    def test_a_malformed_recipients_value_does_not_400(
        self, api_client, website, recipients
    ):
        from apps.scripts.models import Script

        resp = api_client.post(
            "/api/ingest/",
            self._payload(website.site_id, recipients),
            format="json",
        )
        assert resp.status_code == 202
        # Celery runs eagerly in tests, so the scripts posted alongside the
        # malformed `recipients` must have actually been stored, not merely
        # accepted at the HTTP layer.
        assert Script.objects.filter(website=website).exists()
