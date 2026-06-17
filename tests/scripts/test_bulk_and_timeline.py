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
class TestReviewHealsStatus:
    """Reviewing a flagged script clears its open changes so the site heals."""

    def test_single_review_acks_open_change_and_heals(self, auth_client, website):
        s1 = _script(website)
        ScriptChange.objects.create(
            website=website, script=s1, change_type="added", severity="high",
            description="Unknown script detected: https://cdn.x.com/a.js",
        )
        # The open HIGH change drives the site critical.
        from apps.scripts.tasks import _update_website_status
        _update_website_status(website)
        website.refresh_from_db()
        assert website.status == Website.Status.CRITICAL

        resp = auth_client.patch(
            f"/api/v1/websites/{website.pk}/scripts/{s1.id}/review/",
            {"review_status": "approved"},
            format="json",
        )
        assert resp.status_code == 200
        assert ScriptChange.objects.filter(
            script=s1, acknowledged_at__isnull=True
        ).count() == 0
        website.refresh_from_db()
        assert website.status == Website.Status.ACTIVE
        assert website.health_score == 100

    def test_bulk_review_acks_open_changes_and_heals(self, auth_client, website):
        s1 = _script(website, url="https://cdn.x.com/1.js")
        s2 = _script(website, url="https://cdn.x.com/2.js")
        for s in (s1, s2):
            ScriptChange.objects.create(
                website=website, script=s, change_type="added", severity="high",
                description=f"Unknown script detected: {s.src_url}",
            )
        from apps.scripts.tasks import _update_website_status
        _update_website_status(website)
        website.refresh_from_db()
        assert website.status == Website.Status.CRITICAL

        resp = auth_client.post(
            f"/api/v1/websites/{website.pk}/scripts/bulk-review/",
            {"script_ids": [str(s1.id), str(s2.id)], "review_status": "ignored"},
            format="json",
        )
        assert resp.status_code == 200
        assert ScriptChange.objects.filter(
            website=website, acknowledged_at__isnull=True
        ).count() == 0
        website.refresh_from_db()
        assert website.status == Website.Status.ACTIVE
        assert website.health_score == 100


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
