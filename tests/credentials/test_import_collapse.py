"""Reproduces the CSV import collapsing distinct logins into one credential.

A 269-row export landed as 118 credentials. Hypothesis: the duplicate check
keys on (team, website, username_hash) only, so every row that shares a
username is treated as a re-import of the same login — even when the rows are
for completely different services.
"""

import json

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.credentials.models import Credential
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="collapse_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Collapse Agency", owner=owner)


def _client(user):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": user.email, "password": "Pass123!"}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {json.loads(resp.content)['data']['access']}")
    return c


def _csv(rows: str):
    from django.core.files.uploadedfile import SimpleUploadedFile

    header = "url,username,password,totp,extra,name,grouping,fav\n"
    return SimpleUploadedFile("lastpass.csv", (header + rows).encode("utf-8"), content_type="text/csv")


@pytest.mark.django_db
def test_same_username_across_different_services_stays_separate(owner, team):
    """Three different hosting panels, one shared agency login email."""
    rows = (
        "https://hpanel.hostinger.com/login,info@agency.com,pw1,,,Hostinger,Hosting,0\n"
        "https://sso.godaddy.com/,info@agency.com,pw2,,,GoDaddy,Hosting,0\n"
        "https://dash.cloudflare.com/login,info@agency.com,pw3,,,Cloudflare,Hosting,0\n"
    )
    resp = _client(owner).post("/api/v1/credentials/import/", {"file": _csv(rows)}, format="multipart")
    assert resp.status_code == 200, resp.content
    data = json.loads(resp.content)["data"]
    assert data["created"] == 3, data
    assert Credential.objects.filter(team=team).count() == 3


@pytest.mark.django_db
def test_same_username_on_one_website_but_different_services(owner, team):
    """WordPress admin and cPanel on the same client site share an email."""
    Website.objects.create(team=team, name="Acme", domain="acme.io")
    rows = (
        "https://acme.io/wp-admin,admin@acme.io,pw1,,,Acme WordPress,Website Credentials,0\n"
        "https://acme.io:2083/,admin@acme.io,pw2,,,Acme cPanel,Website Credentials,0\n"
    )
    resp = _client(owner).post("/api/v1/credentials/import/", {"file": _csv(rows)}, format="multipart")
    data = json.loads(resp.content)["data"]
    assert data["created"] == 2, data
    assert Credential.objects.filter(team=team).count() == 2
