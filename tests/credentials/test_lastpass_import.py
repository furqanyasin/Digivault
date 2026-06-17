"""Import LastPass CSV export into the credential vault."""

import json

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.credentials.models import Credential
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="lp_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="LP Agency", owner=owner)


def _client(user):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": user.email, "password": "Pass123!"}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {json.loads(resp.content)['data']['access']}")
    return c


def _csv(rows: str) -> "object":
    from django.core.files.uploadedfile import SimpleUploadedFile
    header = "url,username,password,totp,extra,name,grouping,fav\n"
    return SimpleUploadedFile("lastpass.csv", (header + rows).encode("utf-8"), content_type="text/csv")


@pytest.mark.django_db
def test_imports_standalone_and_links_website(owner, team):
    Website.objects.create(team=team, name="Acme", domain="acme.io")
    rows = (
        'https://acme.io/wp-admin,admin,pw1,,note a,Acme WP,Clients,0\n'
        'https://my.siteground.com/login,host,pw2,,,SiteGround,Hosting,0\n'
        'http://sn,,,,"just a note",Secure Note,Notes,0\n'
    )
    resp = _client(owner).post("/api/v1/credentials/import/", {"file": _csv(rows)}, format="multipart")
    assert resp.status_code == 200, resp.content
    data = json.loads(resp.content)["data"]
    assert data["created"] == 2          # the two logins
    assert data["skipped"] == 1          # the secure note (no username/password)

    wp = Credential.objects.get(label="Acme WP")
    assert wp.website is not None and wp.website.domain == "acme.io"
    assert wp.credential_type == "wordpress"

    sg = Credential.objects.get(label="SiteGround")
    assert sg.website is None             # standalone — no matching website
    assert sg.credential_type == "siteground"


@pytest.mark.django_db
def test_reimport_updates_not_duplicates(owner, team):
    rows = 'https://x.com/login,user1,oldpw,,,X Login,,0\n'
    c = _client(owner)
    c.post("/api/v1/credentials/import/", {"file": _csv(rows)}, format="multipart")
    rows2 = 'https://x.com/login,user1,newpw,,,X Login,,0\n'
    resp = c.post("/api/v1/credentials/import/", {"file": _csv(rows2)}, format="multipart")
    data = json.loads(resp.content)["data"]
    assert data["created"] == 0
    assert data["updated"] == 1
    assert Credential.objects.filter(team=team, label="X Login").count() == 1
