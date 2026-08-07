"""Importing a CSV that overlaps the vault asks before it writes.

Re-importing the same sheet used to land a second copy of every login whose URL
or website link had drifted since the first import. The importer now runs a
`preview` pass that reports the overlap, and the commit that follows says what
to do with it: update, skip, or keep both.
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
    return User.objects.create_user(email="dup_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Dup Agency", owner=owner)


@pytest.fixture
def client(owner):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": owner.email, "password": "Pass123!"}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {json.loads(resp.content)['data']['access']}")
    return c


def _csv(rows: str):
    from django.core.files.uploadedfile import SimpleUploadedFile

    header = "url,username,password,totp,extra,name,grouping,fav\n"
    return SimpleUploadedFile("lastpass.csv", (header + rows).encode("utf-8"), content_type="text/csv")


def _post(client, rows: str, mode: str | None = None) -> dict:
    payload = {"file": _csv(rows)}
    if mode:
        payload["mode"] = mode
    resp = client.post("/api/v1/credentials/import/", payload, format="multipart")
    assert resp.status_code == 200, resp.content
    return json.loads(resp.content)["data"]


ROWS = 'https://acme.io/wp-admin,admin@acme.io,pw1,,,Acme WP,Website Credentials,0\n'


@pytest.mark.django_db
def test_preview_reports_the_overlap_and_writes_nothing(client, team):
    _post(client, ROWS)
    assert Credential.objects.filter(team=team).count() == 1

    data = _post(client, ROWS, mode="preview")
    assert data["duplicates"] == 1
    assert data["created"] == 0
    assert data["conflicts"][0]["existing_label"] == "Acme WP"
    # The preview must not touch the vault — that is the whole point of asking.
    assert Credential.objects.filter(team=team).count() == 1
    assert data["conflicts"][0]["username"] == "ad***@acme.io"


@pytest.mark.django_db
def test_preview_counts_new_rows_alongside_duplicates(client, team):
    _post(client, ROWS)
    data = _post(
        client,
        ROWS + "https://other.io/login,me@other.io,pw2,,,Other,Hosting,0\n",
        mode="preview",
    )
    assert (data["rows"], data["created"], data["duplicates"]) == (2, 1, 0 + 1)


@pytest.mark.django_db
def test_skip_mode_leaves_the_existing_login_alone(client, team):
    _post(client, ROWS)
    data = _post(client, 'https://acme.io/wp-admin,admin@acme.io,changed,,,Acme WP,Website Credentials,0\n', mode="skip")
    assert (data["created"], data["updated"], data["skipped"]) == (0, 0, 1)
    cred = Credential.objects.get(team=team)
    assert cred.get_password() == "pw1"


@pytest.mark.django_db
def test_update_mode_refreshes_the_password(client, team):
    _post(client, ROWS)
    data = _post(client, 'https://acme.io/wp-admin,admin@acme.io,changed,,,Acme WP,Website Credentials,0\n', mode="update")
    assert (data["created"], data["updated"]) == (0, 1)
    assert Credential.objects.get(team=team).get_password() == "changed"


@pytest.mark.django_db
def test_duplicate_mode_keeps_both_copies(client, team):
    _post(client, ROWS)
    data = _post(client, ROWS, mode="duplicate")
    assert data["created"] == 1
    assert Credential.objects.filter(team=team, label="Acme WP").count() == 2


@pytest.mark.django_db
def test_same_login_under_a_different_path_is_one_login(client, team):
    """/wp-admin and /wp-login.php on a linked site are the same WordPress admin."""
    Website.objects.create(team=team, name="Acme", domain="acme.io")
    _post(client, ROWS)
    data = _post(
        client,
        'https://acme.io/wp-login.php,admin@acme.io,pw1,,,Acme WP admin,Website Credentials,0\n',
        mode="preview",
    )
    assert data["duplicates"] == 1
    assert Credential.objects.filter(team=team).count() == 1


@pytest.mark.django_db
def test_a_repeat_inside_one_file_is_not_counted_as_a_vault_duplicate(client, team):
    data = _post(client, ROWS + ROWS, mode="preview")
    assert (data["created"], data["duplicates"], data["repeats_in_file"]) == (1, 0, 1)


@pytest.mark.django_db
def test_unknown_mode_is_rejected(client, team):
    resp = client.post(
        "/api/v1/credentials/import/",
        {"file": _csv(ROWS), "mode": "obliterate"},
        format="multipart",
    )
    assert resp.status_code == 400
