"""End-to-end cover for the UI's team toggle: "Let these teams see the password".

Off must still autofill. These exercise the shape the dashboard actually
creates -- a scope="credential" grant, flipped by delete-then-recreate --
rather than the scope="all" grant the other group tests use.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamMembership
from apps.credentials.models import SubTeamCredentialGrant
from apps.credentials.services import CredentialService


@pytest.fixture
def group(db, team):
    return SubTeam.objects.create(team=team, name="Web Team")


@pytest.fixture
def credential(db, team):
    return CredentialService.create(
        team=team, website=None, label="cPanel", credential_type="cpanel",
        login_url="https://host.example.com/login", username="u",
        password="s3cret", notes="", created_by=None,
    )


def _client_for(user):
    c = APIClient()
    resp = c.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SecurePass1!"},
        format="json",
    )
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


@pytest.fixture
def dev(db, django_user_model, team, group):
    u = django_user_model.objects.create_user(
        email="webdev@x.io", password="SecurePass1!"
    )
    TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER, sub_team=group
    )
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u


@pytest.fixture
def owner_client(db, user, team):
    user.active_team = team
    user.save(update_fields=["active_team"])
    user.set_password("SecurePass1!")
    user.save()
    return _client_for(user)


def _grant(owner_client, group, credential, can_view):
    return owner_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {
            "scope": "credential",
            "credential": str(credential.pk),
            "can_view_password": can_view,
        },
        format="json",
    )


@pytest.mark.django_db
def test_single_credential_grant_with_view_off_still_autofills(
    owner_client, group, credential, dev
):
    assert _grant(owner_client, group, credential, False).status_code == 201

    dev_client = _client_for(dev)

    # It has to be listed by the extension, or there is nothing to fill.
    listed = dev_client.get("/api/extension/credentials/?domain=host.example.com")
    assert listed.status_code == 200
    assert [str(c["id"]) for c in listed.data] == [str(credential.pk)]

    # Autofill gets the real password.
    fill = dev_client.post(f"/api/extension/credentials/{credential.pk}/reveal/")
    assert fill.status_code == 200
    assert fill.data["password"] == "s3cret"

    # The dashboard does not.
    view = dev_client.post(f"/api/v1/credentials/{credential.pk}/reveal/")
    assert view.data["password"] == ""
    assert view.data["password_hidden"] is True


@pytest.mark.django_db
def test_flipping_the_toggle_off_leaves_autofill_working(
    owner_client, group, credential, dev
):
    """The UI flips the flag as DELETE + POST. Autofill must survive the round trip."""
    created = _grant(owner_client, group, credential, True)
    assert created.status_code == 201
    grant_id = created.data["id"]

    deleted = owner_client.delete(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/{grant_id}/"
    )
    assert deleted.status_code == 204
    recreated = _grant(owner_client, group, credential, False)
    assert recreated.status_code == 201, recreated.data

    dev_client = _client_for(dev)
    fill = dev_client.post(f"/api/extension/credentials/{credential.pk}/reveal/")
    assert fill.status_code == 200
    assert fill.data["password"] == "s3cret"
