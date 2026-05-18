import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="fixture@example.com", password="SecurePass1!"
    )


@pytest.fixture
def team(user):
    return TeamService.create(name="Fixture Agency", owner=user)


@pytest.fixture
def auth_client(user, team):
    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SecurePass1!"},
        format="json",
    )
    token = response.data["data"]["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def developer_user(db, team):
    dev = User.objects.create_user(email="dev@example.com", password="SecurePass1!")
    TeamMembership.objects.create(
        user=dev, team=team, role=TeamMembership.Role.DEVELOPER
    )
    return dev
