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

    def test_filter_by_multiple_actions(self, auth_client, logs, team, user):
        """?actions= takes a comma list — a named view like "Approvals" spans
        several action types, which a single ?action= cannot express."""
        ActivityLog.objects.create(
            team=team, actor=user, action=ActivityLog.Action.SCRIPT_REVIEWED,
            description="Reviewed a script", resource_type="script",
        )
        resp = auth_client.get(
            "/api/v1/logs/", {"actions": "auth.login,script.reviewed"}
        )
        assert resp.status_code == 200
        assert {row["action"] for row in resp.data} == {"auth.login", "script.reviewed"}

    def test_blank_actions_param_is_ignored(self, auth_client, logs):
        """An empty ?actions= must not filter everything out."""
        resp = auth_client.get("/api/v1/logs/", {"actions": ""})
        assert resp.status_code == 200
        assert len(resp.data) == 2


@pytest.mark.django_db
class TestAuditResourceNames:
    """Website/client columns: the log stores only resource_id + metadata, so
    the names are resolved for the page rather than stored per row."""

    @pytest.fixture
    def site(self, team, django_user_model):
        from apps.clients.models import Client
        from apps.websites.models import Website

        client = Client.objects.create(team=team, name="Acme Ltd", website_url="acme.test")
        return Website.objects.create(
            team=team, name="Acme Site", domain="acme.test", client=client
        )

    def test_website_action_fills_website_column_only(self, auth_client, team, user, site):
        """The two columns are mutually exclusive — a website edit is a website
        event, so the client column stays empty even though a client owns it."""
        ActivityLog.objects.create(
            team=team, actor=user, action=ActivityLog.Action.WEBSITE_UPDATED,
            description="Updated website", resource_type="website", resource_id=str(site.pk),
        )
        row = auth_client.get("/api/v1/logs/").data[0]
        assert row["website_name"] == "Acme Site"
        assert row["client_name"] == ""

    def test_client_action_fills_client_column_only(self, auth_client, team, user, site):
        ActivityLog.objects.create(
            team=team, actor=user, action=ActivityLog.Action.CLIENT_UPDATED,
            description="Updated client", resource_type="client",
            resource_id=str(site.client_id),
        )
        row = auth_client.get("/api/v1/logs/").data[0]
        assert row["client_name"] == "Acme Ltd"
        assert row["website_name"] == ""

    def test_name_from_metadata_website_id(self, auth_client, team, user, site):
        """Script reviews and change acks carry the id in metadata, not resource_id."""
        ActivityLog.objects.create(
            team=team, actor=user, action=ActivityLog.Action.SCRIPT_REVIEWED,
            description="Reviewed a script", resource_type="script",
            resource_id="not-a-website", metadata={"website_id": str(site.pk)},
        )
        row = auth_client.get("/api/v1/logs/").data[0]
        assert row["website_name"] == "Acme Site"
        assert row["client_name"] == ""

    def test_non_uuid_resource_id_does_not_error(self, auth_client, team, user):
        """resource_id is free text — a non-UUID must not blow up the lookup."""
        ActivityLog.objects.create(
            team=team, actor=user, action=ActivityLog.Action.AUTH_LOGIN,
            description="Logged in", resource_type="website", resource_id="session-abc",
        )
        resp = auth_client.get("/api/v1/logs/")
        assert resp.status_code == 200
        assert resp.data[0]["website_name"] == ""

    def test_filter_by_client_covers_its_websites(self, auth_client, team, user, site):
        ActivityLog.objects.create(
            team=team, actor=user, action=ActivityLog.Action.WEBSITE_UPDATED,
            description="On the client's site", resource_type="website",
            resource_id=str(site.pk),
        )
        ActivityLog.objects.create(
            team=team, actor=user, action=ActivityLog.Action.AUTH_LOGIN,
            description="Unrelated", resource_type="session",
        )
        resp = auth_client.get("/api/v1/logs/", {"client_id": str(site.client_id)})
        assert resp.status_code == 200
        assert [r["description"] for r in resp.data] == ["On the client's site"]

    def test_bulk_acknowledge_records_the_website(self, auth_client, team, user, site):
        """Regression: bulk acknowledge logged no website reference at all, so the
        Website column read "—" and ?website_id= never found it."""
        from apps.scripts.models import Script, ScriptChange

        script = Script.objects.create(
            website=site, src_url="https://cdn.test/a.js", src_domain="cdn.test"
        )
        changes = [
            ScriptChange.objects.create(
                website=site, script=script, change_type="added",
                severity="high", description=f"Added script {i}",
            )
            for i in range(3)
        ]
        resp = auth_client.post(
            "/api/v1/changes/bulk-acknowledge/",
            {"change_ids": [str(c.pk) for c in changes]},
            format="json",
        )
        assert resp.status_code == 200

        row = ActivityLog.objects.filter(
            action=ActivityLog.Action.WEBSITE_CHANGE_ACKNOWLEDGED
        ).first()
        assert row.metadata.get("website_id") == str(site.pk)
        assert "3 script change(s)" in row.description
        # And it is reachable through the website filter the UI uses.
        found = auth_client.get("/api/v1/logs/", {"website_id": str(site.pk)}).data
        assert any(r["action"] == "website.change_acknowledged" for r in found)
        assert all(
            r["website_name"] == site.name
            for r in found
            if r["action"] == "website.change_acknowledged"
        )

    def test_filter_by_website(self, auth_client, team, user, site):
        ActivityLog.objects.create(
            team=team, actor=user, action=ActivityLog.Action.WEBSITE_UPDATED,
            description="On the site", resource_type="website", resource_id=str(site.pk),
        )
        ActivityLog.objects.create(
            team=team, actor=user, action=ActivityLog.Action.AUTH_LOGIN,
            description="Unrelated", resource_type="session",
        )
        resp = auth_client.get("/api/v1/logs/", {"website_id": str(site.pk)})
        assert [r["description"] for r in resp.data] == ["On the site"]


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
