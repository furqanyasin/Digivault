"""Deleting a client: refused while it is live, allowed once it is offboarded.

The rule exists because two different jobs were sharing one control. Retiring a
client is offboarding — reversible, keeps the history, and is what should happen
to a client who leaves. Deleting is for a row that should never have existed:
the same client filed twice, which is easy to end up with because the CSV import
matches on `name` exactly (so "HomePro Chesapeake" and "Homepro chesapeake" are
two clients to `update_or_create`) and adding one by hand checks nothing at all.

Requiring OFFBOARDED first is what keeps a live client from being one mis-click
from gone.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.audit.models import ActivityLog
from apps.clients.models import Client
from apps.websites.models import Website


def _client_for(user):
    api = APIClient()
    resp = api.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SecurePass1!"},
        format="json",
    )
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return api


@pytest.mark.django_db
def test_delete_refused_while_client_is_active(auth_client, team):
    client = Client.objects.create(team=team, name="Live Co", status=Client.Status.ACTIVE)

    resp = auth_client.delete(f"/api/v1/clients/{client.id}/")

    assert resp.status_code == 400, resp.data
    assert Client.objects.filter(pk=client.pk).exists()


@pytest.mark.django_db
def test_delete_refused_while_client_is_paused(auth_client, team):
    client = Client.objects.create(team=team, name="Paused Co", status=Client.Status.PAUSED)

    resp = auth_client.delete(f"/api/v1/clients/{client.id}/")

    assert resp.status_code == 400, resp.data
    assert Client.objects.filter(pk=client.pk).exists()


@pytest.mark.django_db
def test_offboarded_client_can_be_deleted(auth_client, team):
    client = Client.objects.create(
        team=team, name="Homepro chesapeake", status=Client.Status.OFFBOARDED
    )

    resp = auth_client.delete(f"/api/v1/clients/{client.id}/")

    assert resp.status_code == 204, resp.data
    assert not Client.objects.filter(pk=client.pk).exists()


@pytest.mark.django_db
def test_deleting_a_client_leaves_its_website_alone(auth_client, team):
    """Website.client is SET_NULL, so the monitored site outlives the record.

    Deleting a duplicate must not take a site's scripts, monitors and history
    with it — and the surviving client adopts the orphan on the next save or
    import (_auto_create_website).
    """
    client = Client.objects.create(
        team=team, name="Dupe Co", website_url="https://dupe.io",
        status=Client.Status.OFFBOARDED,
    )
    website = Website.objects.create(
        team=team, name="Dupe", domain="dupe.io", client=client
    )

    resp = auth_client.delete(f"/api/v1/clients/{client.id}/")
    assert resp.status_code == 204, resp.data

    website.refresh_from_db()
    assert website.client_id is None


@pytest.mark.django_db
def test_delete_is_audited(auth_client, team):
    client = Client.objects.create(
        team=team, name="Audit Co", status=Client.Status.OFFBOARDED
    )

    assert auth_client.delete(f"/api/v1/clients/{client.id}/").status_code == 204

    log = ActivityLog.objects.get(action=ActivityLog.Action.CLIENT_DELETED)
    assert "Audit Co" in log.description


@pytest.mark.django_db
def test_developer_may_not_delete_a_client(team):
    """DELETE is manager-only via TeamRolePermission's `destroy_role` default."""
    dev = User.objects.create_user(email="dev-delete@example.com", password="SecurePass1!")
    TeamMembership.objects.create(user=dev, team=team, role=TeamMembership.Role.DEVELOPER)
    dev.active_team = team
    dev.save(update_fields=["active_team"])

    client = Client.objects.create(
        team=team, name="Off Co", status=Client.Status.OFFBOARDED
    )

    resp = _client_for(dev).delete(f"/api/v1/clients/{client.id}/")

    assert resp.status_code == 403, resp.data
    assert Client.objects.filter(pk=client.pk).exists()


@pytest.mark.django_db
def test_cannot_delete_another_teams_client(auth_client, db):
    """The queryset is team-scoped, so another team's client is simply absent."""
    from apps.accounts.services import TeamService

    other_owner = User.objects.create_user(
        email="other-owner@example.com", password="SecurePass1!"
    )
    other_team = TeamService.create(name="Other Agency", owner=other_owner)
    client = Client.objects.create(
        team=other_team, name="Not Yours", status=Client.Status.OFFBOARDED
    )

    resp = auth_client.delete(f"/api/v1/clients/{client.id}/")

    assert resp.status_code == 404
    assert Client.objects.filter(pk=client.pk).exists()
