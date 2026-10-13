import pytest
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamMembership


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
def manager(db, django_user_model, team):
    u = django_user_model.objects.create_user(email="mgr@x.io", password="SecurePass1!")
    TeamMembership.objects.create(user=u, team=team, role=TeamMembership.Role.MANAGER)
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u


@pytest.fixture
def co_owner(db, django_user_model, team):
    """A second owner — not `team.owner`, but holding the owner role.

    This is what answers the owner-lockout the gate was briefly widened to
    manager for: cover is a person an owner named, not a whole tier.
    """
    u = django_user_model.objects.create_user(email="co@x.io", password="SecurePass1!")
    TeamMembership.objects.create(user=u, team=team, role=TeamMembership.Role.OWNER)
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u


def test_owner_creates_a_group(auth_client, team):
    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/",
        {"name": "Web Team", "description": "Builds and maintains sites"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["name"] == "Web Team"
    assert resp.data["member_count"] == 0


def test_a_co_owner_creates_a_group(co_owner, team):
    """The gate reads the owner *role*, not `team.owner`, so a second owner has
    the same reach as the first. This is the lockout answer: a team that needs
    cover while the owner is away names one person, rather than every manager
    holding the power to widen credential access by default."""
    resp = _client_for(co_owner).post(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/", {"name": "Web Team"}, format="json",
    )
    assert resp.status_code == 201, resp.data
    assert SubTeam.objects.filter(team=team, name="Web Team").exists()


def test_manager_cannot_create_a_group(manager, team):
    """Group admin is owner-only. A manager already reads every credential in
    the team, so what this withholds is not what they see — it is their ability
    to hand that reach to somebody else."""
    resp = _client_for(manager).post(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/", {"name": "Web Team"}, format="json",
    )
    assert resp.status_code == 403, resp.data
    assert not SubTeam.objects.filter(team=team).exists()


def test_manager_can_list_groups(manager, team):
    """Listing stays open to any team member: the group badge on a member row
    is not the access policy, and hiding it would only make the UI lie."""
    SubTeam.objects.create(team=team, name="Web Team")
    resp = _client_for(manager).get(f"/api/v1/auth/teams/{team.pk}/sub-teams/")
    assert resp.status_code == 200
    assert [g["name"] for g in resp.data] == ["Web Team"]


def test_duplicate_group_name_is_rejected(auth_client, team):
    SubTeam.objects.create(team=team, name="Web Team")
    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/", {"name": "Web Team"}, format="json",
    )
    assert resp.status_code == 400


def test_owner_renames_a_group(auth_client, team):
    group = SubTeam.objects.create(team=team, name="Web Team")
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/{group.pk}/",
        {"name": "Website Team"}, format="json",
    )
    assert resp.status_code == 200
    assert resp.data["name"] == "Website Team"


def test_manager_cannot_rename_or_delete_a_group(manager, team):
    group = SubTeam.objects.create(team=team, name="Web Team")
    client = _client_for(manager)
    url = f"/api/v1/auth/teams/{team.pk}/sub-teams/{group.pk}/"
    assert client.patch(url, {"name": "X"}, format="json").status_code == 403
    assert client.delete(url).status_code == 403
    group.refresh_from_db()
    assert group.name == "Web Team"


def test_a_co_owner_renames_and_deletes_a_group(co_owner, team):
    group = SubTeam.objects.create(team=team, name="Web Team")
    client = _client_for(co_owner)
    url = f"/api/v1/auth/teams/{team.pk}/sub-teams/{group.pk}/"
    assert client.patch(url, {"name": "X"}, format="json").status_code == 200
    assert client.delete(url).status_code in (200, 204)
    assert not SubTeam.objects.filter(pk=group.pk).exists()


def test_owner_deletes_a_group_and_members_are_ungrouped(auth_client, team, django_user_model):
    group = SubTeam.objects.create(team=team, name="Web Team")
    u = django_user_model.objects.create_user(email="d@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER, sub_team=group
    )
    resp = auth_client.delete(f"/api/v1/auth/teams/{team.pk}/sub-teams/{group.pk}/")
    assert resp.status_code == 204
    m.refresh_from_db()
    assert m.sub_team_id is None


def test_a_group_from_another_team_is_not_reachable(auth_client, team, django_user_model):
    from apps.accounts.services import TeamService

    other_owner = django_user_model.objects.create_user(email="oo@x.io", password="x")
    other = TeamService.create(name="Other", owner=other_owner)
    foreign = SubTeam.objects.create(team=other, name="Web Team")
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/{foreign.pk}/",
        {"name": "Hijacked"}, format="json",
    )
    assert resp.status_code == 404


def test_owner_sets_a_group_when_creating_a_user(auth_client, team):
    group = SubTeam.objects.create(team=team, name="Web Team")
    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.pk}/users/",
        {
            "email": "new@x.io", "name": "New Dev",
            "role": "developer", "sub_team": str(group.pk),
        },
        format="json",
    )
    assert resp.status_code in (200, 201)
    membership = TeamMembership.objects.get(team=team, user__email="new@x.io")
    assert membership.sub_team_id == group.pk


def test_manager_cannot_set_a_group_when_creating_a_user(manager, team):
    """Refused before the account is touched, so a manager attempting it never
    half-creates a user — and refused visibly rather than having the key
    silently dropped."""
    group = SubTeam.objects.create(team=team, name="Web Team")
    resp = _client_for(manager).post(
        f"/api/v1/auth/teams/{team.pk}/users/",
        {
            "email": "new2@x.io", "name": "N", "role": "developer",
            "sub_team": str(group.pk),
        },
        format="json",
    )
    assert resp.status_code == 403, resp.data
    assert not TeamMembership.objects.filter(
        team=team, user__email="new2@x.io"
    ).exists()


def test_manager_can_still_create_a_user_without_a_group(manager, team):
    resp = _client_for(manager).post(
        f"/api/v1/auth/teams/{team.pk}/users/",
        {"email": "new3@x.io", "name": "N", "role": "developer"},
        format="json",
    )
    assert resp.status_code in (200, 201)


def test_owner_moves_an_existing_member_between_groups(auth_client, team, django_user_model):
    web = SubTeam.objects.create(team=team, name="Web Team")
    seo = SubTeam.objects.create(team=team, name="SEO Team")
    u = django_user_model.objects.create_user(email="mv@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER, sub_team=web
    )
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "developer", "sub_team": str(seo.pk)}, format="json",
    )
    assert resp.status_code == 200
    m.refresh_from_db()
    assert m.sub_team_id == seo.pk
    assert resp.data["sub_team_name"] == "SEO Team"


def test_owner_can_clear_a_members_group(auth_client, team, django_user_model):
    web = SubTeam.objects.create(team=team, name="Web Team")
    u = django_user_model.objects.create_user(email="cl@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER, sub_team=web
    )
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "developer", "sub_team": None}, format="json",
    )
    assert resp.status_code == 200
    m.refresh_from_db()
    assert m.sub_team_id is None


def test_manager_cannot_change_a_members_group(manager, team, django_user_model):
    """A role change is a manager's to make; the credential group that comes
    with it is not. The key is refused rather than dropped, because a permission
    change that did not happen must not look like one that did."""
    web = SubTeam.objects.create(team=team, name="Web Team")
    u = django_user_model.objects.create_user(email="nm@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER
    )
    resp = _client_for(manager).patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "developer", "sub_team": str(web.pk)}, format="json",
    )
    assert resp.status_code == 403, resp.data
    m.refresh_from_db()
    assert m.sub_team_id is None


def test_a_co_owner_changes_a_members_group(co_owner, team, django_user_model):
    web = SubTeam.objects.create(team=team, name="Web Team")
    u = django_user_model.objects.create_user(email="nmco@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER
    )
    resp = _client_for(co_owner).patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "developer", "sub_team": str(web.pk)}, format="json",
    )
    assert resp.status_code == 200, resp.data
    m.refresh_from_db()
    assert m.sub_team_id == web.pk


def test_a_developer_also_cannot_change_a_members_group(
    team, django_user_model
):
    """Pinned separately from the manager case so the refusal is known to come
    from the group gate rather than from the manager floor on the endpoint."""
    web = SubTeam.objects.create(team=team, name="Web Team")
    # The login helper posts "SecurePass1!" — a user created with any other
    # password gets a 401 with no `access` key, which reads as a KeyError
    # rather than as the 403 this test is about.
    dev = django_user_model.objects.create_user(
        email="devgate@x.io", password="SecurePass1!"
    )
    TeamMembership.objects.create(
        user=dev, team=team, role=TeamMembership.Role.DEVELOPER
    )
    dev.active_team = team
    dev.save(update_fields=["active_team"])

    u = django_user_model.objects.create_user(email="nm2@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER
    )
    resp = _client_for(dev).patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "developer", "sub_team": str(web.pk)}, format="json",
    )
    assert resp.status_code == 403
    m.refresh_from_db()
    assert m.sub_team_id is None


def test_manager_can_still_change_a_role_without_touching_the_group(
    manager, team, django_user_model
):
    u = django_user_model.objects.create_user(email="rr@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER
    )
    resp = _client_for(manager).patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "viewer"}, format="json",
    )
    assert resp.status_code == 200
    m.refresh_from_db()
    assert m.role == "viewer"


def test_assigning_a_group_from_another_team_is_rejected(auth_client, team, django_user_model):
    from apps.accounts.services import TeamService

    other_owner = django_user_model.objects.create_user(email="ox@x.io", password="x")
    other = TeamService.create(name="Other", owner=other_owner)
    foreign = SubTeam.objects.create(team=other, name="Web Team")
    u = django_user_model.objects.create_user(email="xt@x.io", password="x")
    m = TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER
    )
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.pk}/members/{m.pk}/",
        {"role": "developer", "sub_team": str(foreign.pk)}, format="json",
    )
    assert resp.status_code == 400
    m.refresh_from_db()
    assert m.sub_team_id is None
