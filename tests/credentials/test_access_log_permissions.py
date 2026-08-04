"""Role enforcement on the credential access log.

GET /api/v1/websites/<website_pk>/credential-audit/ is manager-and-above only.
The view declared `required_role = "manager"` long before `RolePermission` was
actually added to its `permission_classes`, so the gate silently did nothing
and any team member could read who revealed which credential. These tests pin
the behaviour so the permission class cannot be dropped again unnoticed.
"""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership
from apps.accounts.services import TeamService
from apps.websites.models import Website


@pytest.fixture
def team(db, django_user_model):
    owner = django_user_model.objects.create_user(
        email="audit_owner@x.io", password="Pass123!"
    )
    return TeamService.create(name="AuditCo", owner=owner)


@pytest.fixture
def make_user(db, django_user_model):
    def _make(email, team, role):
        u = django_user_model.objects.create_user(email=email, password="Pass123!")
        TeamMembership.objects.create(user=u, team=team, role=role)
        u.active_team = team
        u.save(update_fields=["active_team"])
        return u
    return _make


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Audited", domain="audited.io")


def _client_for(user):
    c = APIClient()
    resp = c.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "Pass123!"},
        format="json",
    )
    assert resp.status_code == 200, f"Token request failed for {user.email}: {resp.data}"
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


@pytest.mark.django_db
def test_manager_can_read_credential_access_log(team, make_user, website):
    manager = make_user("audit_mgr@x.io", team, TeamMembership.Role.MANAGER)
    resp = _client_for(manager).get(f"/api/v1/websites/{website.pk}/credential-audit/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_owner_can_read_credential_access_log(team, website):
    owner = TeamMembership.objects.get(team=team, role=TeamMembership.Role.OWNER).user
    resp = _client_for(owner).get(f"/api/v1/websites/{website.pk}/credential-audit/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_developer_cannot_read_credential_access_log(team, make_user, website):
    dev = make_user("audit_dev@x.io", team, TeamMembership.Role.DEVELOPER)
    resp = _client_for(dev).get(f"/api/v1/websites/{website.pk}/credential-audit/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_viewer_cannot_read_credential_access_log(team, make_user, website):
    viewer = make_user("audit_viewer@x.io", team, TeamMembership.Role.VIEWER)
    resp = _client_for(viewer).get(f"/api/v1/websites/{website.pk}/credential-audit/")
    assert resp.status_code == 403
