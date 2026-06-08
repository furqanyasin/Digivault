"""Phase 3.3 — status page branding, incidents, maintenance windows."""

import datetime

import pytest
from django.utils import timezone

from apps.status_pages.models import (
    MaintenanceWindow,
    StatusPage,
    StatusPageIncident,
)


@pytest.fixture
def page(team):
    return StatusPage.objects.create(
        team=team, name="Status", slug="acme-status", brand_color="#2563eb",
        logo_url="https://acme.io/logo.png",
    )


@pytest.mark.django_db
class TestIncidents:
    def test_create_incident(self, auth_client, page):
        resp = auth_client.post(
            f"/api/v1/status-pages/{page.id}/incidents/",
            {"title": "API outage", "body": "Investigating", "status": "investigating"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["status"] == "investigating"

    def test_resolving_sets_resolved_at(self, auth_client, page):
        inc = StatusPageIncident.objects.create(status_page=page, title="x")
        resp = auth_client.patch(
            f"/api/v1/status-pages/{page.id}/incidents/{inc.id}/",
            {"status": "resolved"},
            format="json",
        )
        assert resp.status_code == 200
        inc.refresh_from_db()
        assert inc.resolved_at is not None

    def test_team_scoped(self, auth_client, page, db):
        from apps.accounts.models import User
        from apps.accounts.services import TeamService

        other = TeamService.create(
            name="Other",
            owner=User.objects.create_user(email="o@sp.com", password="Pass123!"),
        )
        other_page = StatusPage.objects.create(team=other, name="O", slug="o-status")
        resp = auth_client.get(f"/api/v1/status-pages/{other_page.id}/incidents/")
        # team-scoped: page not visible → empty list
        assert resp.status_code == 200
        assert resp.data == []


@pytest.mark.django_db
class TestMaintenance:
    def test_create_and_is_active(self, auth_client, page):
        now = timezone.now()
        resp = auth_client.post(
            f"/api/v1/status-pages/{page.id}/maintenance/",
            {
                "title": "DB upgrade",
                "scheduled_start": (now - datetime.timedelta(hours=1)).isoformat(),
                "scheduled_end": (now + datetime.timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["is_active"] is True


@pytest.mark.django_db
class TestPublicPage:
    def test_public_includes_branding_incidents_maintenance(self, page):
        from rest_framework.test import APIClient

        StatusPageIncident.objects.create(
            status_page=page, title="Active incident", status="investigating"
        )
        now = timezone.now()
        MaintenanceWindow.objects.create(
            status_page=page, title="Upcoming",
            scheduled_start=now + datetime.timedelta(days=1),
            scheduled_end=now + datetime.timedelta(days=1, hours=2),
        )
        client = APIClient()
        resp = client.get(f"/api/v1/public/status/{page.slug}/")
        assert resp.status_code == 200
        assert resp.data["brand_color"] == "#2563eb"
        assert resp.data["logo_url"] == "https://acme.io/logo.png"
        assert len(resp.data["incidents"]) == 1
        assert len(resp.data["maintenance"]) == 1
