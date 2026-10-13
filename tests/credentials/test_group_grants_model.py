import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from apps.accounts.models import SubTeam
from apps.accounts.services import TeamService
from apps.credentials.models import SubTeamCredentialGrant
from apps.credentials.services import CredentialService


@pytest.fixture
def group(db, team):
    return SubTeam.objects.create(team=team, name="Web Team")


@pytest.fixture
def credential(db, team):
    return CredentialService.create(
        team=team, website=None, label="cPanel", credential_type="cpanel",
        login_url="", username="u", password="p", notes="", created_by=None,
    )


def test_grant_defaults_to_no_reveal(group):
    grant = SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    assert grant.can_view_password is False


def test_only_one_blanket_grant_per_group(group):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    with pytest.raises(IntegrityError):
        SubTeamCredentialGrant.objects.create(
            sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
        )


def test_type_grant_is_unique_per_group_and_type(group):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE,
        credential_type="cpanel",
    )
    with pytest.raises(IntegrityError):
        SubTeamCredentialGrant.objects.create(
            sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE,
            credential_type="cpanel",
        )


def test_blanket_grant_rejects_a_target(group, credential):
    grant = SubTeamCredentialGrant(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL,
        credential=credential,
    )
    with pytest.raises(ValidationError):
        grant.full_clean()


def test_type_grant_requires_a_credential_type(group):
    grant = SubTeamCredentialGrant(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE
    )
    with pytest.raises(ValidationError):
        grant.full_clean()


def test_credential_grant_requires_a_credential(group):
    grant = SubTeamCredentialGrant(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL
    )
    with pytest.raises(ValidationError):
        grant.full_clean()


def test_credential_grant_rejects_a_credential_from_another_team(group, django_user_model):
    other_owner = django_user_model.objects.create_user(email="o2@x.io", password="x")
    other_team = TeamService.create(name="Other", owner=other_owner)
    foreign = CredentialService.create(
        team=other_team, website=None, label="Foreign", credential_type="cpanel",
        login_url="", username="u", password="p", notes="", created_by=None,
    )
    grant = SubTeamCredentialGrant(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL,
        credential=foreign,
    )
    with pytest.raises(ValidationError):
        grant.full_clean()


def test_deleting_the_credential_removes_its_grant(group, credential):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.CREDENTIAL,
        credential=credential,
    )
    credential.delete()
    assert not SubTeamCredentialGrant.objects.exists()


def test_deleting_the_group_removes_its_grants(group):
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    group.delete()
    assert not SubTeamCredentialGrant.objects.exists()
