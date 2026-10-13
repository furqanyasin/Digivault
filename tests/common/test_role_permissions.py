"""A viewer may read the product. A viewer may not change it.

`RolePermission` shipped with a four-tier hierarchy and was wired to four views
out of roughly a hundred, so the role column was decorative almost everywhere: a
viewer could create and delete websites and monitors, rename the department,
write alert rules, import and export the whole client book, and rotate a site's
tracking id — which stops ingest on the client's live site until someone
re-pastes the snippet.

The reason it went unused is worth keeping in view: `RolePermission` gates every
method at one level, and nearly every view here both reads and writes, so
applying it would have taken the viewer's *read* access away too.
`TeamRolePermission` splits on method, which is what makes it applicable at all.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor
from apps.websites.models import Website


def _client_for(user):
    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SecurePass1!"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return client


def _member(team, email, role):
    user = User.objects.create_user(email=email, password="SecurePass1!")
    TeamMembership.objects.create(user=user, team=team, role=role)
    user.active_team = team
    user.save(update_fields=["active_team"])
    return user


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="rbac_owner@test.com", password="SecurePass1!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="RBAC Agency", owner=owner)


@pytest.fixture
def viewer_client(team):
    return _client_for(_member(team, "rbac_viewer@test.com", TeamMembership.Role.VIEWER))


@pytest.fixture
def developer_client(team):
    return _client_for(
        _member(team, "rbac_dev@test.com", TeamMembership.Role.DEVELOPER)
    )


@pytest.fixture
def manager_client(team):
    return _client_for(
        _member(team, "rbac_mgr@test.com", TeamMembership.Role.MANAGER)
    )


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="RBAC Site", domain="rbac.test")


pytestmark = pytest.mark.django_db


class TestViewerIsReadOnly:
    def test_viewer_can_read_websites(self, viewer_client, website):
        assert viewer_client.get("/api/v1/websites/").status_code == 200

    def test_viewer_cannot_create_a_website(self, viewer_client):
        response = viewer_client.post(
            "/api/v1/websites/",
            {"name": "Sneaky", "domain": "sneaky.test"},
            format="json",
        )
        assert response.status_code == 403

    def test_viewer_cannot_delete_a_website(self, viewer_client, website):
        response = viewer_client.delete(f"/api/v1/websites/{website.id}/")
        assert response.status_code == 403
        assert Website.objects.filter(pk=website.pk).exists()

    def test_viewer_cannot_create_a_monitor(self, viewer_client):
        response = viewer_client.post(
            "/api/v1/monitors/",
            {"name": "M", "url": "https://rbac.test", "monitor_type": "http"},
            format="json",
        )
        assert response.status_code == 403

    def test_viewer_cannot_create_an_alert_rule(self, viewer_client):
        response = viewer_client.post(
            "/api/v1/alert-rules/",
            {"channel": "in_app", "min_severity": "low"},
            format="json",
        )
        assert response.status_code == 403

    def test_viewer_cannot_rename_the_team(self, viewer_client, team):
        response = viewer_client.patch(
            f"/api/v1/auth/teams/{team.id}/", {"name": "Renamed"}, format="json"
        )
        assert response.status_code == 403

    def test_viewer_cannot_export_the_client_book(self, viewer_client):
        assert viewer_client.get("/api/v1/clients/export/").status_code == 403

    def test_viewer_cannot_rotate_a_site_id(self, viewer_client, website):
        """The most disruptive button in the product: ingest stops until re-paste."""
        before = website.site_id
        response = viewer_client.post(
            f"/api/v1/websites/{website.id}/regenerate-snippet/"
        )
        assert response.status_code == 403
        website.refresh_from_db()
        assert website.site_id == before


class TestDeveloperDoesTheWork:
    def test_developer_can_create_a_monitor(self, developer_client):
        response = developer_client.post(
            "/api/v1/monitors/",
            {"name": "M", "url": "https://rbac.test", "monitor_type": "http"},
            format="json",
        )
        assert response.status_code == 201, response.data

    def test_developer_can_create_a_website(self, developer_client):
        response = developer_client.post(
            "/api/v1/websites/",
            {"name": "Built", "domain": "built.test"},
            format="json",
        )
        assert response.status_code == 201, response.data

    def test_developer_cannot_delete_a_monitor(self, developer_client, team):
        """Deletes are structural — they take the history with them."""
        monitor = Monitor.objects.create(
            team=team, name="M", url="https://rbac.test", monitor_type="http"
        )
        response = developer_client.delete(f"/api/v1/monitors/{monitor.id}/")
        assert response.status_code == 403
        assert Monitor.objects.filter(pk=monitor.pk).exists()

    def test_developer_cannot_rotate_a_site_id(self, developer_client, website):
        response = developer_client.post(
            f"/api/v1/websites/{website.id}/regenerate-snippet/"
        )
        assert response.status_code == 403


class TestManagerCanDoTheStructuralThings:
    def test_manager_can_delete_a_monitor(self, manager_client, team):
        monitor = Monitor.objects.create(
            team=team, name="M", url="https://rbac.test", monitor_type="http"
        )
        response = manager_client.delete(f"/api/v1/monitors/{monitor.id}/")
        assert response.status_code == 204
        assert not Monitor.objects.filter(pk=monitor.pk).exists()

    def test_manager_can_rotate_a_site_id(self, manager_client, website):
        before = website.site_id
        response = manager_client.post(
            f"/api/v1/websites/{website.id}/regenerate-snippet/"
        )
        assert response.status_code == 200, response.data
        website.refresh_from_db()
        assert website.site_id != before
