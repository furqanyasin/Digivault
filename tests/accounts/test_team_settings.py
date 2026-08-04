"""Team integration settings — the ClickUp token and issue list.

The PATCH handler used to read `clickup_api_token` unconditionally, so any
request that did not resend it wiped the stored token. Now that a second field
lives on the same endpoint, that is a live hazard: saving a list id would log
the team out of ClickUp. These pin both fields as independently updatable.
"""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="settings_owner@x.io", password="Pass123!")


@pytest.fixture
def team(db, owner):
    return TeamService.create(name="SettingsCo", owner=owner)


@pytest.fixture
def client_as_owner(db, owner, team):
    owner.active_team = team
    owner.save(update_fields=["active_team"])
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": owner.email, "password": "Pass123!"}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


def test_list_id_can_be_saved(client_as_owner, team):
    resp = client_as_owner.patch(
        f"/api/v1/auth/teams/{team.pk}/settings/", {"clickup_list_id": "901234"}, format="json"
    )

    assert resp.status_code == 200
    team.refresh_from_db()
    assert team.clickup_list_id == "901234"


def test_saving_the_list_id_does_not_wipe_the_stored_token(client_as_owner, team):
    team.clickup_api_token = "pk_keepme"
    team.save()

    client_as_owner.patch(
        f"/api/v1/auth/teams/{team.pk}/settings/", {"clickup_list_id": "901234"}, format="json"
    )

    team.refresh_from_db()
    assert team.clickup_api_token == "pk_keepme"
    assert team.clickup_list_id == "901234"


def test_saving_the_token_does_not_wipe_the_stored_list_id(client_as_owner, team):
    team.clickup_list_id = "555"
    team.save()

    client_as_owner.patch(
        f"/api/v1/auth/teams/{team.pk}/settings/", {"clickup_api_token": "pk_new"}, format="json"
    )

    team.refresh_from_db()
    assert team.clickup_list_id == "555"
    assert team.clickup_api_token == "pk_new"


def test_the_list_id_is_returned_so_the_settings_form_can_show_it(client_as_owner, team):
    team.clickup_list_id = "424242"
    team.save()

    resp = client_as_owner.get(f"/api/v1/auth/teams/{team.pk}/settings/")

    assert resp.data["clickup_list_id"] == "424242"


def test_a_developer_cannot_change_integration_settings(db, team, django_user_model):
    dev = django_user_model.objects.create_user(email="settings_dev@x.io", password="Pass123!")
    TeamMembership.objects.create(user=dev, team=team, role="developer")
    dev.active_team = team
    dev.save(update_fields=["active_team"])
    c = APIClient()
    tok = c.post("/api/v1/auth/token/", {"email": dev.email, "password": "Pass123!"}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok.data['access']}")

    resp = c.patch(f"/api/v1/auth/teams/{team.pk}/settings/", {"clickup_list_id": "nope"}, format="json")

    assert resp.status_code == 403
    team.refresh_from_db()
    assert team.clickup_list_id == ""
