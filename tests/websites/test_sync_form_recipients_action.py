"""The manual "read where my forms deliver" button.

It used to hard-fail with "Set up WP Connect for this website first" on every
site without the PHP snippet. Now WP Connect is only the first of two paths, and
the 409 is reserved for a site that has neither.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.credentials.models import Credential
from apps.websites.models import Website

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="sfr_o@test.com", password="Pass123!")
    return TeamService.create(name="Sync Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Sync Site", domain="syncform.test")


@pytest.fixture
def client_for(team):
    owner = team.owner
    owner.active_team = team
    owner.save(update_fields=["active_team"])
    client = APIClient()
    client.force_authenticate(user=owner)
    return client


def _url(website):
    return f"/api/v1/websites/{website.pk}/sync-form-recipients/"


def _wp_credential(team, website):
    cred = Credential(
        team=team,
        website=website,
        label="wp",
        credential_type=Credential.CredentialType.WORDPRESS,
    )
    cred.set_username("admin")
    cred.set_password("hunter2")
    cred.save()
    return cred


def test_409_when_neither_path_is_available(client_for, website):
    resp = client_for.post(_url(website))

    assert resp.status_code == 409
    assert "WordPress credentials" in resp.data["detail"]


def test_falls_back_to_the_api_path_without_wp_connect(
    client_for, website, team, monkeypatch
):
    _wp_credential(team, website)
    monkeypatch.setattr("apps.websites.wp_api_forms.sync_website", lambda site: 2)

    resp = client_for.post(_url(website))

    assert resp.status_code == 200
    assert resp.data["updated"] == 2
    assert resp.data["source"] == "wp_api"


def test_wp_connect_still_wins_when_configured(client_for, website, team, monkeypatch):
    """A credential is present too, but the stronger source must be chosen."""
    _wp_credential(team, website)
    website.wp_sso_secret = "s3cret"
    website.save(update_fields=["wp_sso_secret"])
    monkeypatch.setattr("apps.websites.wp_forms.sync_website", lambda site: 5)

    resp = client_for.post(_url(website))

    assert resp.data["updated"] == 5
    assert resp.data["source"] == "wordpress"


def test_a_reader_blowing_up_reports_502(client_for, website, team, monkeypatch):
    _wp_credential(team, website)

    def _boom(site):
        raise RuntimeError("nope")

    monkeypatch.setattr("apps.websites.wp_api_forms.sync_website", _boom)

    resp = client_for.post(_url(website))

    assert resp.status_code == 502
