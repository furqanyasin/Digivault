import pytest
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamMembership
from apps.credentials.models import SubTeamCredentialGrant
from apps.credentials.services import CredentialService


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
def group(db, team):
    return SubTeam.objects.create(team=team, name="Web Team")


@pytest.fixture
def manager(db, django_user_model, team):
    u = django_user_model.objects.create_user(email="mgr2@x.io", password="SecurePass1!")
    TeamMembership.objects.create(user=u, team=team, role=TeamMembership.Role.MANAGER)
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u


@pytest.fixture
def co_owner(db, django_user_model, team):
    """A second owner — holds the owner role but is not `team.owner`."""
    u = django_user_model.objects.create_user(email="co2@x.io", password="SecurePass1!")
    TeamMembership.objects.create(user=u, team=team, role=TeamMembership.Role.OWNER)
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u


@pytest.fixture
def credential(db, team):
    return CredentialService.create(
        team=team, website=None, label="cPanel", credential_type="cpanel",
        login_url="", username="u", password="p", notes="", created_by=None,
    )


def test_owner_creates_a_blanket_grant(auth_client, group):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "all"}, format="json",
    )
    assert resp.status_code == 201
    assert resp.data["scope"] == "all"
    assert resp.data["can_view_password"] is False


def test_reveal_must_be_asked_for_explicitly(auth_client, group):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "all", "can_view_password": True}, format="json",
    )
    assert resp.data["can_view_password"] is True


def test_owner_creates_a_type_grant(auth_client, group):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "type", "credential_type": "cpanel"}, format="json",
    )
    assert resp.status_code == 201
    assert resp.data["credential_type"] == "cpanel"


def test_type_grant_rejects_an_unknown_credential_type(auth_client, group):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "type", "credential_type": "not_a_type"}, format="json",
    )
    assert resp.status_code == 400


def test_owner_creates_a_single_credential_grant(auth_client, group, credential):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "credential", "credential": str(credential.pk)}, format="json",
    )
    assert resp.status_code == 201
    assert resp.data["credential_label"] == "cPanel"


def test_blanket_grant_rejects_a_target(auth_client, group, credential):
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "all", "credential": str(credential.pk)}, format="json",
    )
    assert resp.status_code == 400


def test_duplicate_blanket_grant_is_rejected(auth_client, group):
    auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/", {"scope": "all"}, format="json",
    )
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/", {"scope": "all"}, format="json",
    )
    assert resp.status_code == 400


def test_manager_cannot_create_or_list_grants(manager, group):
    """Granting is owner-only, reading included: the grant list *is* the access
    policy. A manager already reads every credential in the team, so the gate
    does not change what they see — it withholds the power to give that reach to
    somebody else."""
    client = _client_for(manager)
    assert client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/", {"scope": "all"},
        format="json",
    ).status_code == 403
    assert not SubTeamCredentialGrant.objects.exists()

    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    assert client.get(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/"
    ).status_code == 403


def test_a_co_owner_creates_and_lists_grants(co_owner, group):
    """The gate reads the owner role, so a second owner administers grants just
    as the first does — which is what covers an absent owner now."""
    client = _client_for(co_owner)
    resp = client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/", {"scope": "all"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    listed = client.get(f"/api/v1/sub-teams/{group.pk}/credential-grants/")
    assert listed.status_code == 200
    assert len(listed.data) == 1


def test_a_developer_also_cannot_touch_grants(team, django_user_model, group):
    """Pinned below the manager case so a refusal there is known to be the owner
    gate rather than a floor the endpoint happens to have anyway."""
    from apps.accounts.models import TeamMembership

    # Logging in is how this test reaches the gate, so the password has to be
    # the one `_client_for` posts.
    dev = django_user_model.objects.create_user(
        email="grant_dev@x.io", password="SecurePass1!"
    )
    TeamMembership.objects.create(
        user=dev, team=team, role=TeamMembership.Role.DEVELOPER
    )
    dev.active_team = team
    dev.save(update_fields=["active_team"])
    client = _client_for(dev)

    assert client.get(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/"
    ).status_code == 403
    assert client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/", {"scope": "all"},
        format="json",
    ).status_code == 403


def test_owner_lists_grants(auth_client, group):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    resp = auth_client.get(f"/api/v1/sub-teams/{group.pk}/credential-grants/")
    assert resp.status_code == 200
    assert len(resp.data) == 1


def test_owner_revokes_a_grant(auth_client, group):
    grant = SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    resp = auth_client.delete(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/{grant.pk}/"
    )
    assert resp.status_code == 204
    assert not SubTeamCredentialGrant.objects.exists()


def test_manager_cannot_revoke_a_grant(manager, group):
    """Every grant verb reads one predicate (`is_group_admin`), so revoke cannot
    drift away from create and list the way five inline copies of the role check
    once did."""
    grant = SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    resp = _client_for(manager).delete(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/{grant.pk}/"
    )
    assert resp.status_code == 403
    assert SubTeamCredentialGrant.objects.exists()


def test_a_co_owner_revokes_a_grant(co_owner, group):
    grant = SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    resp = _client_for(co_owner).delete(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/{grant.pk}/"
    )
    assert resp.status_code == 204, resp.data
    assert not SubTeamCredentialGrant.objects.exists()


def test_a_group_in_another_team_is_not_reachable(auth_client, django_user_model):
    from apps.accounts.services import TeamService

    other_owner = django_user_model.objects.create_user(email="oy@x.io", password="x")
    other = TeamService.create(name="Other", owner=other_owner)
    foreign = SubTeam.objects.create(team=other, name="Web Team")
    resp = auth_client.post(
        f"/api/v1/sub-teams/{foreign.pk}/credential-grants/", {"scope": "all"}, format="json",
    )
    assert resp.status_code == 404


def test_credential_grant_from_another_team_is_rejected(auth_client, group, django_user_model):
    from apps.accounts.services import TeamService

    other_owner = django_user_model.objects.create_user(email="oz@x.io", password="x")
    other = TeamService.create(name="Other", owner=other_owner)
    foreign = CredentialService.create(
        team=other, website=None, label="F", credential_type="cpanel",
        login_url="", username="u", password="p", notes="", created_by=None,
    )
    resp = auth_client.post(
        f"/api/v1/sub-teams/{group.pk}/credential-grants/",
        {"scope": "credential", "credential": str(foreign.pk)}, format="json",
    )
    assert resp.status_code == 400


def test_per_credential_grants_are_listed_for_one_credential(auth_client, group, credential):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL, credential=credential,
    )
    resp = auth_client.get(f"/api/v1/credentials/{credential.pk}/group-grants/")
    assert resp.status_code == 200
    assert resp.data[0]["sub_team_name"] == "Web Team"


def test_shares_endpoint_still_returns_a_bare_array(auth_client, credential):
    """Response shape is load-bearing: the deployed frontend expects a list."""
    resp = auth_client.get(f"/api/v1/credentials/{credential.pk}/shares/")
    assert resp.status_code == 200
    assert isinstance(resp.data, list)
