import uuid

import pytest

from apps.accounts.models import Team, TeamInvitation, TeamMembership, User


@pytest.mark.django_db
class TestUserModel:
    def test_create_user_sets_email_as_username(self):
        user = User.objects.create_user(
            email="alice@example.com", password="TestPass123!"
        )
        assert user.email == "alice@example.com"
        assert user.username == "alice@example.com"

    def test_create_user_password_is_hashed(self):
        user = User.objects.create_user(
            email="bob@example.com", password="TestPass123!"
        )
        assert user.check_password("TestPass123!")
        assert not user.check_password("WrongPassword")

    def test_create_superuser(self):
        user = User.objects.create_superuser(
            email="admin@example.com", password="AdminPass123!"
        )
        assert user.is_staff
        assert user.is_superuser

    def test_pk_is_uuid(self):
        user = User.objects.create_user(
            email="uuid@example.com", password="TestPass123!"
        )
        assert isinstance(user.pk, uuid.UUID)

    def test_str_returns_email(self):
        user = User.objects.create_user(
            email="str@example.com", password="TestPass123!"
        )
        assert str(user) == "str@example.com"


@pytest.mark.django_db
class TestTeamModel:
    def test_team_creation(self):
        owner = User.objects.create_user(email="owner@acme.com", password="Pass123!")
        team = Team.objects.create(name="Acme Agency", owner=owner)
        assert str(team) == "Acme Agency"
        assert team.slug  # auto-generated

    def test_slug_is_unique(self):
        owner = User.objects.create_user(email="o1@acme.com", password="Pass123!")
        owner2 = User.objects.create_user(email="o2@acme.com", password="Pass123!")
        t1 = Team.objects.create(name="Acme", owner=owner)
        t2 = Team.objects.create(name="Acme", owner=owner2)
        assert t1.slug != t2.slug


@pytest.mark.django_db
class TestTeamMembership:
    def test_owner_membership_created_on_team_save(self):
        owner = User.objects.create_user(email="owner@test.com", password="Pass123!")
        team = Team.objects.create(name="Test Agency", owner=owner)
        assert TeamMembership.objects.filter(
            user=owner, team=team, role=TeamMembership.Role.OWNER
        ).exists()

    def test_role_choices(self):
        roles = [r.value for r in TeamMembership.Role]
        assert set(roles) == {"owner", "manager", "developer", "viewer"}


@pytest.mark.django_db
class TestTeamInvitation:
    def test_token_auto_generated(self):
        owner = User.objects.create_user(email="inv@test.com", password="Pass123!")
        team = Team.objects.create(name="Invite Team", owner=owner)
        invitation = TeamInvitation.objects.create(
            team=team,
            invited_by=owner,
            email="new@member.com",
            role=TeamMembership.Role.DEVELOPER,
        )
        assert len(invitation.token) > 20

    def test_str_representation(self):
        owner = User.objects.create_user(email="str_inv@test.com", password="Pass123!")
        team = Team.objects.create(name="StrTeam", owner=owner)
        invitation = TeamInvitation.objects.create(
            team=team,
            invited_by=owner,
            email="x@y.com",
        )
        assert "x@y.com" in str(invitation)
        assert "StrTeam" in str(invitation)
