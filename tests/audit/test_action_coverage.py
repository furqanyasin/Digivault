"""Every significant user trigger writes an ActivityLog row.

These cover the actions that previously left no audit trail — the cause of
'Your activity — 0 events' for users whose work was all in untracked views.
"""

import pytest

from apps.audit.models import ActivityLog
from apps.scripts.models import Script
from apps.websites.models import Website


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Audit Site", domain="audit.io")


@pytest.mark.django_db
class TestActionCoverage:
    def test_script_review_logged(self, auth_client, website):
        script = Script.objects.create(
            website=website, src_url="https://x.io/a.js", src_domain="x.io",
            provider="unknown", is_active=True,
        )
        resp = auth_client.patch(
            f"/api/v1/websites/{website.pk}/scripts/{script.pk}/review/",
            {"review_status": "approved"},
            format="json",
        )
        assert resp.status_code == 200
        log = ActivityLog.objects.get(action=ActivityLog.Action.SCRIPT_REVIEWED)
        assert "approved" in log.description

    def test_bulk_script_review_logged(self, auth_client, website):
        s1 = Script.objects.create(
            website=website, src_url="https://x.io/1.js", src_domain="x.io",
            provider="unknown", is_active=True,
        )
        resp = auth_client.post(
            f"/api/v1/websites/{website.pk}/scripts/bulk-review/",
            {"script_ids": [str(s1.pk)], "review_status": "ignored"},
            format="json",
        )
        assert resp.status_code == 200
        assert ActivityLog.objects.filter(
            action=ActivityLog.Action.SCRIPT_REVIEWED
        ).exists()

    def test_monitor_create_pause_resume_logged(self, auth_client):
        resp = auth_client.post(
            "/api/v1/monitors/",
            {"name": "Audit Mon", "url": "https://audit.io", "monitor_type": "http"},
            format="json",
        )
        assert resp.status_code == 201
        monitor_id = resp.data["id"]
        assert ActivityLog.objects.filter(action=ActivityLog.Action.MONITOR_CREATED).exists()

        assert auth_client.post(f"/api/v1/monitors/{monitor_id}/pause/").status_code == 200
        assert ActivityLog.objects.filter(action=ActivityLog.Action.MONITOR_PAUSED).exists()

        assert auth_client.post(f"/api/v1/monitors/{monitor_id}/resume/").status_code == 200
        assert ActivityLog.objects.filter(action=ActivityLog.Action.MONITOR_RESUMED).exists()

    def test_website_delete_logged(self, auth_client, website):
        resp = auth_client.delete(f"/api/v1/websites/{website.pk}/")
        assert resp.status_code == 204
        log = ActivityLog.objects.get(action=ActivityLog.Action.WEBSITE_DELETED)
        assert "audit.io" in log.description

    def test_status_page_create_delete_logged(self, auth_client):
        resp = auth_client.post(
            "/api/v1/status-pages/",
            {"name": "Audit Status", "slug": "audit-status", "description": ""},
            format="json",
        )
        assert resp.status_code == 201
        page_id = resp.data["id"]
        assert ActivityLog.objects.filter(action=ActivityLog.Action.STATUS_PAGE_CREATED).exists()

        assert auth_client.delete(f"/api/v1/status-pages/{page_id}/").status_code == 204
        assert ActivityLog.objects.filter(action=ActivityLog.Action.STATUS_PAGE_DELETED).exists()
