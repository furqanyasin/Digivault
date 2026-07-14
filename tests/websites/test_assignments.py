"""Per-website user assignment — queryset enforcement and the assignments API."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.websites.models import Website, WebsiteAssignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="asg_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Asg Agency", owner=owner)


@pytest.fixture
def developer(team):
    dev = User.objects.create_user(email="asg_dev@test.com", password="Pass123!")
    TeamMembership.objects.create(user=dev, team=team, role="developer")
    dev.active_team = team
    dev.save(update_fields=["active_team"])
    return dev


@pytest.fixture
def sites(team):
    return [
        Website.objects.create(team=team, name=f"Site {i}", domain=f"s{i}.asg.io")
        for i in range(3)
    ]


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestQuerysetEnforcement:
    def test_unassigned_developer_sees_all(self, developer, sites):
        resp = _client(developer).get("/api/v1/websites/")
        assert resp.status_code == 200
        assert len(resp.data) == 3

    def test_assigned_developer_sees_only_assigned(self, developer, sites):
        WebsiteAssignment.objects.create(website=sites[0], user=developer)
        resp = _client(developer).get("/api/v1/websites/")
        assert len(resp.data) == 1
        assert resp.data[0]["id"] == str(sites[0].id)

        # Detail access to an unassigned site 404s — enforced, not hidden.
        detail = _client(developer).get(f"/api/v1/websites/{sites[1].id}/")
        assert detail.status_code == 404

    def test_owner_unaffected_by_assignments(self, owner, developer, sites):
        WebsiteAssignment.objects.create(website=sites[0], user=developer)
        owner.active_team = sites[0].team
        owner.save(update_fields=["active_team"])
        resp = _client(owner).get("/api/v1/websites/")
        assert len(resp.data) == 3


class TestAssignmentsEndpoint:
    def test_owner_replaces_assignment_set(self, owner, developer, sites, team):
        owner.active_team = team
        owner.save(update_fields=["active_team"])
        url = f"/api/v1/websites/{sites[0].id}/assignments/"

        resp = _client(owner).put(url, {"user_ids": [str(developer.id)]}, format="json")
        assert resp.status_code == 200, resp.data
        assert [r["email"] for r in resp.data["assigned"]] == ["asg_dev@test.com"]
        assert resp.data["can_edit"] is True
        member_emails = {m["email"] for m in resp.data["members"]}
        assert "asg_dev@test.com" in member_emails

        # Replacing with an empty list clears assignments.
        resp = _client(owner).put(url, {"user_ids": []}, format="json")
        assert resp.data["assigned"] == []

    def test_developer_cannot_assign(self, developer, sites):
        WebsiteAssignment.objects.create(website=sites[0], user=developer)
        url = f"/api/v1/websites/{sites[0].id}/assignments/"
        resp = _client(developer).put(url, {"user_ids": []}, format="json")
        assert resp.status_code == 403

    def test_non_member_rejected(self, owner, sites, team):
        owner.active_team = team
        owner.save(update_fields=["active_team"])
        outsider = User.objects.create_user(email="asg_out@test.com", password="Pass123!")
        url = f"/api/v1/websites/{sites[0].id}/assignments/"
        resp = _client(owner).put(url, {"user_ids": [str(outsider.id)]}, format="json")
        assert resp.status_code == 400
