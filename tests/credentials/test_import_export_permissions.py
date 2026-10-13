"""Import and export are owner/manager only, and export round-trips back in."""

import json

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.credentials.models import Credential, CredentialAccessLog
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="exp_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Export Agency", owner=owner)


def _member(team, email, role):
    user = User.objects.create_user(email=email, password="Pass123!")
    TeamMembership.objects.create(team=team, user=user, role=role)
    user.active_team = team
    user.save(update_fields=["active_team"])
    return user


def _client(user):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": user.email, "password": "Pass123!"}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {json.loads(resp.content)['data']['access']}")
    return c


def _csv(rows: str):
    from django.core.files.uploadedfile import SimpleUploadedFile

    header = "url,username,password,totp,extra,name,grouping,fav\n"
    return SimpleUploadedFile("lastpass.csv", (header + rows).encode("utf-8"), content_type="text/csv")


_ROWS = (
    "https://acme.io/wp-admin,admin@acme.io,pw1,,note one,Acme WordPress,Website Credentials,0\n"
    "https://hpanel.hostinger.com/,info@agency.com,pw2,,,Hostinger,Hosting,0\n"
)


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["developer", "editor", "seo", "viewer"])
def test_import_and_export_forbidden_below_manager(owner, team, role):
    user = _member(team, f"{role}_ie@test.com", role)
    c = _client(user)
    assert c.post("/api/v1/credentials/import/", {"file": _csv(_ROWS)}, format="multipart").status_code == 403
    assert c.get("/api/v1/credentials/export/").status_code == 403


@pytest.mark.django_db
def test_manager_may_import_and_export(owner, team):
    manager = _member(team, "manager_ie@test.com", "manager")
    c = _client(manager)
    assert c.post("/api/v1/credentials/import/", {"file": _csv(_ROWS)}, format="multipart").status_code == 200
    assert c.get("/api/v1/credentials/export/").status_code == 200


@pytest.mark.django_db
def test_export_round_trips_through_import(owner, team):
    Website.objects.create(team=team, name="Acme", domain="acme.io")
    c = _client(owner)
    c.post("/api/v1/credentials/import/", {"file": _csv(_ROWS)}, format="multipart")
    assert Credential.objects.filter(team=team).count() == 2

    resp = c.get("/api/v1/credentials/export/")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    body = resp.content.decode("utf-8-sig")
    assert "Acme WordPress" in body and "pw1" in body
    # The exact type and the website link, not a two-value grouping the importer
    # would have to guess back from.
    assert "Acme WordPress,wordpress,acme.io," in body
    assert "Hostinger,hostinger,," in body

    # Feeding the export straight back in updates, never duplicates.
    from django.core.files.uploadedfile import SimpleUploadedFile

    again = c.post(
        "/api/v1/credentials/import/",
        {"file": SimpleUploadedFile("export.csv", body.encode("utf-8"), content_type="text/csv")},
        format="multipart",
    )
    data = json.loads(again.content)["data"]
    assert data["created"] == 0, data
    assert data["updated"] == 2, data
    assert Credential.objects.filter(team=team).count() == 2


@pytest.mark.django_db
def test_export_is_logged_against_every_credential(owner, team):
    c = _client(owner)
    c.post("/api/v1/credentials/import/", {"file": _csv(_ROWS)}, format="multipart")
    CredentialAccessLog.objects.all().delete()

    c.get("/api/v1/credentials/export/")
    logged = CredentialAccessLog.objects.filter(user=owner, action="viewed")
    assert logged.count() == 2


@pytest.mark.django_db
def test_import_reports_row_total_and_survives_a_bad_row(owner, team):
    """An over-long URL keeps its data in notes instead of killing the import."""
    long_url = "https://example.com/" + "x" * 600
    rows = (
        _ROWS
        + f"{long_url},someone@agency.com,pw3,,,Long URL Login,Hosting,0\n"
        + "http://sn,,,,just a note,Secure Note,Notes,0\n"
    )
    resp = _client(owner).post("/api/v1/credentials/import/", {"file": _csv(rows)}, format="multipart")
    data = json.loads(resp.content)["data"]
    assert data["rows"] == 4, data
    assert data["created"] == 3, data
    assert data["skipped"] == 1, data
    assert data["failed"] == 0, data

    cred = Credential.objects.get(team=team, label="Long URL Login")
    assert cred.login_url == ""
    assert long_url in cred.get_notes()
