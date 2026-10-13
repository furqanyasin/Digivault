"""One-click WP admin login — secret rotation, token issuance, role mapping."""

import base64
import hashlib
import hmac
import json
import time

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.websites.models import Website

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(db):
    return User.objects.create_user(
        email="sso_owner@test.com", password="Pass123!", first_name="Olive", last_name="Owner"
    )


@pytest.fixture
def team(owner):
    return TeamService.create(name="SSO Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="SSO Site", domain="sso.io")


@pytest.fixture
def developer(team):
    dev = User.objects.create_user(email="sso_dev@test.com", password="Pass123!")
    TeamMembership.objects.create(user=dev, team=team, role="developer")
    dev.active_team = team
    dev.save(update_fields=["active_team"])
    return dev


@pytest.fixture
def viewer(team):
    v = User.objects.create_user(email="sso_view@test.com", password="Pass123!")
    TeamMembership.objects.create(user=v, team=team, role="viewer")
    v.active_team = team
    v.save(update_fields=["active_team"])
    return v


def _client(user, team):
    user.active_team = team
    user.save(update_fields=["active_team"])
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _decode_url(url: str, secret: str) -> dict:
    query = url.split("?", 1)[1]
    params = dict(p.split("=", 1) for p in query.split("&"))
    expected = hmac.new(secret.encode(), params["p"].encode(), hashlib.sha256).hexdigest()
    assert expected == params["s"], "signature must verify with the site secret"
    padded = params["p"] + "=" * (-len(params["p"]) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


class TestSecretRotation:
    def test_owner_generates_secret(self, owner, team, website):
        resp = _client(owner, team).post(f"/api/v1/websites/{website.id}/wp-sso-secret/")
        assert resp.status_code == 200
        assert len(resp.data["secret"]) > 30
        website.refresh_from_db()
        assert website.wp_sso_secret == resp.data["secret"]
        # The response includes a ready-to-paste PHP snippet with the secret in it.
        assert "register_rest_route" in resp.data["snippet"]
        assert resp.data["secret"] in resp.data["snippet"]
        assert "digivault/v1" in resp.data["snippet"]

    def test_developer_cannot_rotate(self, developer, team, website):
        resp = _client(developer, team).post(f"/api/v1/websites/{website.id}/wp-sso-secret/")
        assert resp.status_code == 403


class TestShowSnippet:
    """A re-paste (the uptime heartbeat) must not rotate a working secret."""

    def test_get_returns_current_snippet_without_rotating(self, owner, team, website):
        from apps.audit.models import ActivityLog

        Website.objects.filter(pk=website.pk).update(wp_sso_secret="keep-this-secret")
        resp = _client(owner, team).get(f"/api/v1/websites/{website.id}/wp-sso-secret/")
        assert resp.status_code == 200
        assert "keep-this-secret" in resp.data["snippet"]
        assert "dvc2_cron_tick" in resp.data["snippet"]
        website.refresh_from_db()
        assert website.wp_sso_secret == "keep-this-secret"
        # It carries the secret, so reading it is audited.
        assert ActivityLog.objects.filter(
            action=ActivityLog.Action.WEBSITE_WP_SNIPPET_VIEWED, resource_id=str(website.pk),
        ).exists()

    def test_get_before_any_secret_is_404(self, owner, team, website):
        resp = _client(owner, team).get(f"/api/v1/websites/{website.id}/wp-sso-secret/")
        assert resp.status_code == 404

    def test_developer_cannot_view(self, developer, team, website):
        Website.objects.filter(pk=website.pk).update(wp_sso_secret="keep-this-secret")
        resp = _client(developer, team).get(f"/api/v1/websites/{website.id}/wp-sso-secret/")
        assert resp.status_code == 403


class TestLoginUrl:
    def test_owner_gets_administrator_link(self, owner, team, website):
        Website.objects.filter(pk=website.pk).update(wp_sso_secret="topsecret")
        resp = _client(owner, team).post(f"/api/v1/websites/{website.id}/wp-login/")
        assert resp.status_code == 200, resp.data
        assert resp.data["wp_role"] == "administrator"
        assert resp.data["url"].startswith("https://sso.io/wp-json/digivault/v1/sso?p=")

        payload = _decode_url(resp.data["url"], "topsecret")
        assert payload["email"] == "sso_owner@test.com"
        assert payload["role"] == "administrator"
        assert payload["exp"] > int(time.time())
        assert len(payload["jti"]) == 32

    def test_developer_maps_to_editor(self, developer, team, website):
        Website.objects.filter(pk=website.pk).update(wp_sso_secret="topsecret")
        resp = _client(developer, team).post(f"/api/v1/websites/{website.id}/wp-login/")
        assert resp.status_code == 200
        assert resp.data["wp_role"] == "editor"

    def test_viewer_forbidden(self, viewer, team, website):
        Website.objects.filter(pk=website.pk).update(wp_sso_secret="topsecret")
        resp = _client(viewer, team).post(f"/api/v1/websites/{website.id}/wp-login/")
        assert resp.status_code == 403

    def test_unconfigured_site_conflicts(self, owner, team, website):
        resp = _client(owner, team).post(f"/api/v1/websites/{website.id}/wp-login/")
        assert resp.status_code == 409

    def test_jti_unique_per_link(self, owner, team, website):
        Website.objects.filter(pk=website.pk).update(wp_sso_secret="topsecret")
        client = _client(owner, team)
        a = _decode_url(client.post(f"/api/v1/websites/{website.id}/wp-login/").data["url"], "topsecret")
        b = _decode_url(client.post(f"/api/v1/websites/{website.id}/wp-login/").data["url"], "topsecret")
        assert a["jti"] != b["jti"]
