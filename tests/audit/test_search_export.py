"""Phase 1.6 — audit log search + CSV export."""

import pytest

from apps.audit.models import ActivityLog


@pytest.fixture
def logs(team, user):
    ActivityLog.objects.create(
        team=team, actor=user, action=ActivityLog.Action.AUTH_LOGIN,
        description="Logged in", resource_type="session",
    )
    ActivityLog.objects.create(
        team=team, actor=user, action=ActivityLog.Action.CREDENTIAL_REVEALED,
        description="Revealed WP admin", resource_type="credential",
    )
    return team


@pytest.mark.django_db
class TestAuditSearch:
    def test_filter_by_action(self, auth_client, logs):
        resp = auth_client.get("/api/v1/logs/", {"action": "auth.login"})
        assert resp.status_code == 200
        assert all(row["action"] == "auth.login" for row in resp.data)
        assert len(resp.data) == 1

    def test_filter_by_resource_type(self, auth_client, logs):
        resp = auth_client.get("/api/v1/logs/", {"resource_type": "credential"})
        assert resp.status_code == 200
        assert len(resp.data) == 1

    def test_text_search(self, auth_client, logs):
        resp = auth_client.get("/api/v1/logs/", {"q": "revealed"})
        assert resp.status_code == 200
        assert len(resp.data) == 1
        assert "Revealed" in resp.data[0]["description"]

    def test_no_filter_returns_all(self, auth_client, logs):
        resp = auth_client.get("/api/v1/logs/")
        assert resp.status_code == 200
        assert len(resp.data) == 2


@pytest.mark.django_db
class TestAuditExport:
    def test_csv_export(self, auth_client, logs):
        resp = auth_client.get("/api/v1/logs/export/")
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/csv")
        body = resp.content.decode()
        assert "action" in body  # header row
        assert "auth.login" in body
        assert "credential.revealed" in body

    def test_csv_export_respects_filter(self, auth_client, logs):
        resp = auth_client.get("/api/v1/logs/export/", {"action": "auth.login"})
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "auth.login" in body
        assert "credential.revealed" not in body
