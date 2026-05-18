import json
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="handoff@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Handoff Agency", owner=owner)


def _auth_client(user):
    client = APIClient()
    resp = client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "Pass123!"},
        format="json",
    )
    token = json.loads(resp.content)["data"]["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
class TestWebHandoff:
    def test_unauthenticated_returns_401(self):
        resp = APIClient().post("/api/extension/web-handoff/")
        assert resp.status_code == 401

    def test_returns_code_for_authenticated_user(self, owner, team):
        resp = _auth_client(owner).post("/api/extension/web-handoff/")
        assert resp.status_code == 200
        body = json.loads(resp.content)
        assert "code" in body["data"]
        assert len(body["data"]["code"]) == 32  # uuid4 hex

    def test_code_stored_in_cache(self, owner, team):
        resp = _auth_client(owner).post("/api/extension/web-handoff/")
        code = json.loads(resp.content)["data"]["code"]
        stored = cache.get(f"ext_handoff:{code}")
        assert stored is not None
        assert "access" in stored
        assert "refresh" in stored


@pytest.mark.django_db
class TestWebHandoffExchange:
    def test_missing_code_returns_400(self):
        resp = APIClient().get("/api/extension/exchange/")
        assert resp.status_code == 400

    def test_unknown_code_returns_404(self):
        resp = APIClient().get("/api/extension/exchange/", {"code": "doesnotexist"})
        assert resp.status_code == 404

    def test_valid_code_returns_tokens(self, owner, team):
        handoff_resp = _auth_client(owner).post("/api/extension/web-handoff/")
        code = json.loads(handoff_resp.content)["data"]["code"]

        exchange_resp = APIClient().get("/api/extension/exchange/", {"code": code})
        assert exchange_resp.status_code == 200
        body = json.loads(exchange_resp.content)["data"]
        assert "access" in body
        assert "refresh" in body

    def test_code_deleted_after_exchange(self, owner, team):
        handoff_resp = _auth_client(owner).post("/api/extension/web-handoff/")
        code = json.loads(handoff_resp.content)["data"]["code"]

        APIClient().get("/api/extension/exchange/", {"code": code})
        second = APIClient().get("/api/extension/exchange/", {"code": code})
        assert second.status_code == 404

    def test_no_auth_required_for_exchange(self, owner, team):
        handoff_resp = _auth_client(owner).post("/api/extension/web-handoff/")
        code = json.loads(handoff_resp.content)["data"]["code"]
        resp = APIClient().get("/api/extension/exchange/", {"code": code})
        assert resp.status_code == 200
