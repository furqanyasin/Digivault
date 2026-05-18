import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Team, TeamMembership, User
from apps.accounts.services import TeamService


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def registered_user(db):
    return User.objects.create_user(
        email="test@example.com", password="SecurePass1!"
    )


@pytest.fixture
def auth_client(registered_user):
    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"email": "test@example.com", "password": "SecurePass1!"},
        format="json",
    )
    token = response.data["data"]["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
class TestRegistration:
    def test_register_creates_user(self, api_client):
        response = api_client.post(
            "/api/v1/auth/register/",
            {"email": "new@user.com", "password": "SecurePass1!", "name": "New User"},
            format="json",
        )
        assert response.status_code == 201
        assert User.objects.filter(email="new@user.com").exists()

    def test_response_is_enveloped(self, api_client):
        response = api_client.post(
            "/api/v1/auth/register/",
            {
                "email": "env@user.com",
                "password": "SecurePass1!",
                "name": "Env User",
            },
            format="json",
        )
        assert "data" in response.data
        assert "errors" in response.data

    def test_duplicate_email_returns_400(self, api_client, registered_user):
        response = api_client.post(
            "/api/v1/auth/register/",
            {
                "email": "test@example.com",
                "password": "SecurePass1!",
                "name": "Dupe",
            },
            format="json",
        )
        assert response.status_code == 400

    def test_weak_password_returns_400(self, api_client):
        response = api_client.post(
            "/api/v1/auth/register/",
            {"email": "weak@pass.com", "password": "123", "name": "Weak"},
            format="json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestTokenObtain:
    def test_valid_credentials_return_tokens(self, api_client, registered_user):
        response = api_client.post(
            "/api/v1/auth/token/",
            {"email": "test@example.com", "password": "SecurePass1!"},
            format="json",
        )
        assert response.status_code == 200
        assert "access" in response.data["data"]
        assert "refresh" in response.data["data"]

    def test_invalid_password_returns_401(self, api_client, registered_user):
        response = api_client.post(
            "/api/v1/auth/token/",
            {"email": "test@example.com", "password": "WrongPass"},
            format="json",
        )
        assert response.status_code == 401


@pytest.mark.django_db
class TestMeEndpoint:
    def test_me_returns_current_user(self, auth_client, registered_user):
        response = auth_client.get("/api/v1/auth/me/")
        assert response.status_code == 200
        assert response.data["data"]["email"] == registered_user.email

    def test_me_unauthenticated_returns_401(self, api_client):
        response = api_client.get("/api/v1/auth/me/")
        assert response.status_code == 401


@pytest.mark.django_db
class TestTeamAPI:
    def test_create_team(self, auth_client):
        response = auth_client.post(
            "/api/v1/auth/teams/",
            {"name": "My Agency"},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["data"]["name"] == "My Agency"

    def test_list_teams_returns_only_user_teams(
        self, auth_client, registered_user
    ):
        TeamService.create(name="My Team", owner=registered_user)
        other_owner = User.objects.create_user(
            email="other@example.com", password="Pass1234!"
        )
        TeamService.create(name="Other Team", owner=other_owner)
        response = auth_client.get("/api/v1/auth/teams/")
        names = [t["name"] for t in response.data["data"]]
        assert "My Team" in names
        assert "Other Team" not in names

    def test_list_team_members(self, auth_client, registered_user):
        team = TeamService.create(name="Member Team", owner=registered_user)
        dev = User.objects.create_user(email="dev@example.com", password="Pass1234!")
        TeamService.add_member(
            team=team, user=dev, role=TeamMembership.Role.DEVELOPER
        )
        response = auth_client.get(f"/api/v1/auth/teams/{team.pk}/members/")
        assert response.status_code == 200
        emails = [m["user"]["email"] for m in response.data["data"]]
        assert registered_user.email in emails
        assert "dev@example.com" in emails
