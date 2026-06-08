import pytest

from apps.accounts.models import TeamMembership
from apps.credentials.models import Credential, CredentialShare
from apps.credentials.services import CredentialService


@pytest.fixture
def team(db, django_user_model):
    from apps.accounts.services import TeamService
    owner = django_user_model.objects.create_user(email="acme_owner@x.io", password="x")
    return TeamService.create(name="Acme", owner=owner)


@pytest.fixture
def make_user(db, django_user_model):
    def _make(email, team, role):
        u = django_user_model.objects.create_user(email=email, password="x")
        TeamMembership.objects.create(user=u, team=team, role=role)
        u.active_team = team
        u.save(update_fields=["active_team"])
        return u
    return _make


@pytest.fixture
def cred(team, make_user):
    creator = make_user("creator@x.io", team, TeamMembership.Role.DEVELOPER)
    return CredentialService.create(
        team=team, website=None, label="DB",
        credential_type="custom", login_url="",
        username="u", password="p", notes="",
        created_by=creator,
    )


def test_owner_sees_all(team, make_user, cred):
    owner = make_user("owner@x.io", team, TeamMembership.Role.OWNER)
    assert Credential.objects.visible_to(owner).filter(pk=cred.pk).exists()


def test_manager_sees_all(team, make_user, cred):
    mgr = make_user("mgr@x.io", team, TeamMembership.Role.MANAGER)
    assert Credential.objects.visible_to(mgr).filter(pk=cred.pk).exists()


def test_creator_sees_own(cred):
    creator = cred.created_by
    assert Credential.objects.visible_to(creator).filter(pk=cred.pk).exists()


def test_unrelated_developer_does_not_see(team, make_user, cred):
    dev = make_user("dev@x.io", team, TeamMembership.Role.DEVELOPER)
    assert not Credential.objects.visible_to(dev).filter(pk=cred.pk).exists()


def test_shared_developer_sees(team, make_user, cred):
    dev = make_user("dev@x.io", team, TeamMembership.Role.DEVELOPER)
    CredentialShare.objects.create(credential=cred, user=dev)
    assert Credential.objects.visible_to(dev).filter(pk=cred.pk).exists()


def test_anon_sees_nothing(cred, django_user_model):
    from django.contrib.auth.models import AnonymousUser
    assert not Credential.objects.visible_to(AnonymousUser()).exists()
