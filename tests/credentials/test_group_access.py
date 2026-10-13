import pytest

from apps.accounts.models import SubTeam, TeamMembership
from apps.credentials.models import Credential, SubTeamCredentialGrant
from apps.credentials.services import CredentialService


@pytest.fixture
def group(db, team):
    return SubTeam.objects.create(team=team, name="Web Team")


@pytest.fixture
def grouped_dev(db, django_user_model, team, group):
    u = django_user_model.objects.create_user(email="webdev@x.io", password="x")
    TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER, sub_team=group
    )
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u


def _make_cred(team, label="cPanel", credential_type="cpanel"):
    return CredentialService.create(
        team=team, website=None, label=label, credential_type=credential_type,
        login_url="", username="u", password="p", notes="", created_by=None,
    )


def test_ungrouped_developer_sees_nothing(team, django_user_model):
    dev = django_user_model.objects.create_user(email="plain@x.io", password="x")
    TeamMembership.objects.create(user=dev, team=team, role=TeamMembership.Role.DEVELOPER)
    _make_cred(team)
    assert not Credential.objects.visible_to(dev).exists()


def test_grouped_developer_with_no_grant_sees_nothing(team, grouped_dev):
    _make_cred(team)
    assert not Credential.objects.visible_to(grouped_dev).exists()


def test_blanket_grant_shows_every_credential(team, group, grouped_dev):
    _make_cred(team, "cPanel", "cpanel")
    _make_cred(team, "WP", "wordpress")
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    assert Credential.objects.visible_to(grouped_dev).count() == 2


def test_blanket_grant_covers_a_credential_created_afterwards(team, group, grouped_dev):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    later = _make_cred(team, "Added later", "ftp")
    assert Credential.objects.visible_to(grouped_dev).filter(pk=later.pk).exists()


def test_type_grant_matches_only_that_type(team, group, grouped_dev):
    cpanel = _make_cred(team, "cPanel", "cpanel")
    _make_cred(team, "WP", "wordpress")
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE,
        credential_type="cpanel",
    )
    visible = Credential.objects.visible_to(grouped_dev)
    assert list(visible.values_list("pk", flat=True)) == [cpanel.pk]


def test_single_credential_grant_matches_only_that_credential(team, group, grouped_dev):
    one = _make_cred(team, "One", "cpanel")
    _make_cred(team, "Two", "cpanel")
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL, credential=one,
    )
    visible = Credential.objects.visible_to(grouped_dev)
    assert list(visible.values_list("pk", flat=True)) == [one.pk]


def test_removing_the_member_from_the_group_revokes_access(team, group, grouped_dev):
    _make_cred(team)
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    assert Credential.objects.visible_to(grouped_dev).exists()
    TeamMembership.objects.filter(user=grouped_dev).update(sub_team=None)
    assert not Credential.objects.visible_to(grouped_dev).exists()


def test_deleting_the_group_revokes_access(team, group, grouped_dev):
    _make_cred(team)
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    group.delete()
    assert not Credential.objects.visible_to(grouped_dev).exists()


def test_a_grant_never_leaks_across_teams(team, group, grouped_dev, django_user_model):
    from apps.accounts.services import TeamService

    other_owner = django_user_model.objects.create_user(email="o3@x.io", password="x")
    other_team = TeamService.create(name="Other", owner=other_owner)
    foreign = _make_cred(other_team, "Foreign", "cpanel")
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    assert not Credential.objects.visible_to(grouped_dev).filter(pk=foreign.pk).exists()


def test_no_duplicate_rows_when_two_grants_overlap(team, group, grouped_dev):
    cred = _make_cred(team, "cPanel", "cpanel")
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL, credential=cred,
    )
    assert Credential.objects.visible_to(grouped_dev).count() == 1


def test_extension_lookup_honours_a_group_grant(team, group, grouped_dev):
    """The extension reads the same visible_to gate, in both of its modes."""
    from rest_framework.test import APIClient

    cred = _make_cred(team, "cPanel", "cpanel")
    cred.login_url = "https://client.example.com/cpanel"
    cred.save(update_fields=["login_url"])
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    grouped_dev.set_password("SecurePass1!")
    grouped_dev.save(update_fields=["password"])

    client = APIClient()
    token = client.post(
        "/api/v1/auth/token/",
        {"email": grouped_dev.email, "password": "SecurePass1!"},
        format="json",
    ).data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    all_items = client.get("/api/extension/credentials/?all=1")
    assert [c["id"] for c in all_items.data] == [str(cred.pk)]

    by_domain = client.get("/api/extension/credentials/?domain=client.example.com")
    assert [c["id"] for c in by_domain.data] == [str(cred.pk)]
