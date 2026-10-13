import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from apps.accounts.models import SubTeam, TeamMembership
from apps.accounts.services import TeamService


@pytest.fixture
def other_team(db, django_user_model):
    owner = django_user_model.objects.create_user(email="other@x.io", password="x")
    return TeamService.create(name="Other Agency", owner=owner)


@pytest.fixture
def member(db, django_user_model, team):
    u = django_user_model.objects.create_user(email="web1@x.io", password="x")
    return TeamMembership.objects.create(
        user=u, team=team, role=TeamMembership.Role.DEVELOPER
    )


def test_group_name_is_unique_within_a_team(team):
    SubTeam.objects.create(team=team, name="Web Team")
    with pytest.raises(IntegrityError):
        SubTeam.objects.create(team=team, name="Web Team")


def test_same_group_name_is_allowed_in_another_team(team, other_team):
    SubTeam.objects.create(team=team, name="Web Team")
    assert SubTeam.objects.create(team=other_team, name="Web Team").pk


def test_membership_rejects_a_group_from_another_team(team, other_team, member):
    foreign = SubTeam.objects.create(team=other_team, name="Web Team")
    member.sub_team = foreign
    with pytest.raises(ValidationError):
        member.full_clean()


def test_membership_accepts_a_group_from_its_own_team(team, member):
    member.sub_team = SubTeam.objects.create(team=team, name="Web Team")
    member.full_clean()  # must not raise
    member.save(update_fields=["sub_team"])
    member.refresh_from_db()
    assert member.sub_team.name == "Web Team"


def test_deleting_a_group_ungroups_its_members(team, member):
    member.sub_team = SubTeam.objects.create(team=team, name="Web Team")
    member.save(update_fields=["sub_team"])
    SubTeam.objects.filter(team=team, name="Web Team").delete()
    member.refresh_from_db()
    assert member.sub_team_id is None


def test_existing_memberships_start_ungrouped(member):
    assert member.sub_team_id is None
