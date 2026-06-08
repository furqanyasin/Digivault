"""Phase 1.3 — bulk script review + per-script change timeline."""

import pytest

from apps.scripts.models import Script, ScriptChange
from apps.websites.models import Website


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="S", domain="bulk.io")


def _script(website, status="pending", url="https://cdn.x.com/a.js"):
    return Script.objects.create(
        website=website,
        src_url=url,
        src_domain="cdn.x.com",
        review_status=status,
        is_active=True,
    )


@pytest.mark.django_db
class TestBulkReview:
    def test_bulk_approve_updates_all(self, auth_client, website):
        s1 = _script(website, url="https://cdn.x.com/1.js")
        s2 = _script(website, url="https://cdn.x.com/2.js")
        resp = auth_client.post(
            f"/api/v1/websites/{website.pk}/scripts/bulk-review/",
            {"script_ids": [str(s1.id), str(s2.id)], "review_status": "approved"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["updated"] == 2
        s1.refresh_from_db()
        s2.refresh_from_db()
        assert s1.review_status == "approved"
        assert s2.review_status == "approved"

    def test_invalid_status_rejected(self, auth_client, website):
        s1 = _script(website)
        resp = auth_client.post(
            f"/api/v1/websites/{website.pk}/scripts/bulk-review/",
            {"script_ids": [str(s1.id)], "review_status": "bogus"},
            format="json",
        )
        assert resp.status_code == 400

    def test_only_affects_own_team_scripts(self, auth_client, website, db):
        from apps.accounts.models import User
        from apps.accounts.services import TeamService

        other_team = TeamService.create(
            name="Other",
            owner=User.objects.create_user(email="o@bulk.com", password="Pass123!"),
        )
        other_site = Website.objects.create(team=other_team, name="O", domain="o.io")
        foreign = _script(other_site)
        resp = auth_client.post(
            f"/api/v1/websites/{website.pk}/scripts/bulk-review/",
            {"script_ids": [str(foreign.id)], "review_status": "approved"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["updated"] == 0
        foreign.refresh_from_db()
        assert foreign.review_status == "pending"


@pytest.mark.django_db
class TestScriptTimeline:
    def test_timeline_returns_changes_for_script(self, auth_client, website):
        s1 = _script(website)
        ScriptChange.objects.create(
            website=website, script=s1, change_type="added", severity="high",
            description="added",
        )
        ScriptChange.objects.create(
            website=website, script=s1, change_type="url_changed", severity="medium",
            description="url changed",
        )
        resp = auth_client.get(
            f"/api/v1/websites/{website.pk}/scripts/{s1.id}/timeline/"
        )
        assert resp.status_code == 200
        assert len(resp.data) == 2
