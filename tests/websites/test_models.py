import pytest

from apps.accounts.services import TeamService
from apps.accounts.models import User
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="wo@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Web Agency", owner=owner)


@pytest.mark.django_db
class TestWebsiteModel:
    def test_site_id_auto_generated(self, team):
        site = Website.objects.create(
            team=team, name="Acme", domain="acme.com", platform=Website.Platform.WORDPRESS
        )
        assert site.site_id
        assert len(site.site_id) >= 32

    def test_site_ids_are_unique(self, team):
        s1 = Website.objects.create(team=team, name="S1", domain="s1.com")
        s2 = Website.objects.create(team=team, name="S2", domain="s2.com")
        assert s1.site_id != s2.site_id

    def test_snippet_html_contains_site_id(self, team):
        site = Website.objects.create(team=team, name="Snip", domain="snip.com")
        assert site.site_id in site.snippet_html
        assert "async" in site.snippet_html

    def test_regenerate_site_id_changes_value(self, team):
        site = Website.objects.create(team=team, name="Regen", domain="regen.com")
        old_id = site.site_id
        site.regenerate_site_id()
        assert site.site_id != old_id

    def test_str_representation(self, team):
        site = Website.objects.create(team=team, name="My Site", domain="mysite.io")
        assert "My Site" in str(site)
        assert "mysite.io" in str(site)


@pytest.mark.django_db
class TestWebsiteAPI:
    def _make_client(self, user):
        from rest_framework.test import APIClient
        client = APIClient()
        resp = client.post(
            "/api/v1/auth/token/",
            {"email": user.email, "password": "Pass123!"},
            format="json",
        )
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {resp.data['data']['access']}"
        )
        return client

    def test_create_website(self, owner, team):
        client = self._make_client(owner)
        resp = client.post(
            "/api/v1/websites/",
            {"name": "Client A", "domain": "clienta.com", "platform": "wordpress"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["data"]["name"] == "Client A"

    def test_list_websites_scoped_to_team(self, owner, team):
        Website.objects.create(team=team, name="Mine", domain="mine.com")
        other_owner = User.objects.create_user(
            email="other_wo@test.com", password="Pass123!"
        )
        other_team = TeamService.create(name="Other Agency", owner=other_owner)
        Website.objects.create(team=other_team, name="Theirs", domain="theirs.com")

        client = self._make_client(owner)
        resp = client.get("/api/v1/websites/")
        names = [w["name"] for w in resp.data["data"]]
        assert "Mine" in names
        assert "Theirs" not in names

    def test_snippet_endpoint(self, owner, team):
        site = Website.objects.create(team=team, name="SnipSite", domain="snip.io")
        client = self._make_client(owner)
        resp = client.get(f"/api/v1/websites/{site.pk}/snippet/")
        assert resp.status_code == 200
        assert site.site_id in resp.data["data"]["snippet"]

    def test_regenerate_snippet(self, owner, team):
        site = Website.objects.create(team=team, name="Regen", domain="regen.io")
        old_id = site.site_id
        client = self._make_client(owner)
        resp = client.post(f"/api/v1/websites/{site.pk}/regenerate-snippet/")
        assert resp.status_code == 200
        assert resp.data["data"]["site_id"] != old_id
