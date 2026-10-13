"""The vault CSV carries every writable credential field, plus group access.

The importer historically read a LastPass export's own eight columns, so a
Digivault export could not round-trip: `credential_type` was re-guessed from the
URL, the website link survived only when the login URL happened to sit on the
site's own host, and group grants had no column at all. These tests pin the
native header, the LastPass fallback that still has to work, and the owner-only
`teams` column.
"""

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamMembership, User
from apps.accounts.services import TeamService
from apps.credentials.models import Credential, SubTeamCredentialGrant
from apps.credentials.services import CredentialService
from apps.websites.models import Website

NATIVE_HEADER = "name,credential_type,website,url,username,password,notes,teams"
# What the export writes. The import still takes NATIVE_HEADER alone — a file
# exported before `department` and `totp` existed must keep importing.
EXPORT_HEADER = NATIVE_HEADER + ",department,totp,folder"
LASTPASS_HEADER = "url,username,password,totp,extra,name,grouping,fav"


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="csv_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="CSV Agency", owner=owner)


@pytest.fixture
def site(team):
    return Website.objects.create(team=team, name="Acme", domain="acme.io")


def _member(team, email, role):
    user = User.objects.create_user(email=email, password="Pass123!")
    TeamMembership.objects.create(team=team, user=user, role=role)
    user.active_team = team
    user.save(update_fields=["active_team"])
    return user


def _client(user):
    c = APIClient()
    resp = c.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "Pass123!"},
        format="json",
    )
    token = json.loads(resp.content)["data"]["access"]
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


def _upload(header: str, rows: str, name: str = "vault.csv"):
    body = (header + "\n" + rows).encode("utf-8")
    return SimpleUploadedFile(name, body, content_type="text/csv")


def _import(client, header, rows, **extra):
    resp = client.post(
        "/api/v1/credentials/import/",
        {"file": _upload(header, rows), **extra},
        format="multipart",
    )
    return resp, json.loads(resp.content).get("data") or json.loads(resp.content)


def _export_text(client):
    resp = client.get("/api/v1/credentials/export/")
    assert resp.status_code == 200, resp.content
    return resp.content.decode("utf-8-sig")


def _export_rows(client):
    """Export parsed as dicts, header included as `.fieldnames`."""
    import csv
    import io

    reader = csv.DictReader(io.StringIO(_export_text(client)))
    return reader.fieldnames, list(reader)


# ── The header ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_export_header_is_every_writable_vault_field(owner, team):
    fields, _ = _export_rows(_client(owner))
    assert fields == EXPORT_HEADER.split(",")


# ── Native columns round-trip ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_export_writes_the_exact_credential_type_not_a_grouping(owner, team, site):
    CredentialService.create(
        label="Acme App Password",
        credential_type="wordpress_app_password",
        login_url="https://acme.io/wp-admin",
        username="admin@acme.io",
        password="pw1",
        notes="",
        created_by=owner,
        team=team,
        website=site,
    )
    _, rows = _export_rows(_client(owner))
    assert rows[0]["credential_type"] == "wordpress_app_password"
    assert rows[0]["website"] == "acme.io"


@pytest.mark.django_db
def test_reimported_export_keeps_a_type_the_url_guesser_would_lose(owner, team, site):
    """`ftp` is in no URL hint, so the old export re-imported as `custom`."""
    CredentialService.create(
        label="Acme SFTP",
        credential_type="ftp",
        login_url="https://acme.io:2222/",
        username="deploy",
        password="pw2",
        notes="",
        created_by=owner,
        team=team,
        website=site,
    )
    c = _client(owner)
    body = _export_text(c)

    resp = c.post(
        "/api/v1/credentials/import/",
        {"file": SimpleUploadedFile("export.csv", body.encode("utf-8"), content_type="text/csv")},
        format="multipart",
    )
    assert resp.status_code == 200, resp.content
    cred = Credential.objects.get(team=team, label="Acme SFTP")
    assert cred.credential_type == "ftp"


@pytest.mark.django_db
def test_website_column_links_a_login_hosted_off_the_site_domain(owner, team, site):
    """A hosting panel login for acme.io lives on my.siteground.com.

    Host matching can never recover that link; the explicit column can.
    """
    rows = "Acme Hosting,siteground,acme.io,https://my.siteground.com,ops@agency.com,pw3,,\n"
    resp, data = _import(_client(owner), NATIVE_HEADER, rows)
    assert resp.status_code == 200, resp.content
    assert data["created"] == 1, data

    cred = Credential.objects.get(team=team, label="Acme Hosting")
    assert cred.website_id == site.id


@pytest.mark.django_db
def test_website_column_tolerates_scheme_and_www(owner, team, site):
    """The URL is deliberately off-domain, so only the column can resolve it."""
    rows = "Acme Panel,cpanel,https://www.acme.io/,https://panel.hosting.net,ops,pw,,\n"
    _import(_client(owner), NATIVE_HEADER, rows)
    assert Credential.objects.get(team=team, label="Acme Panel").website_id == site.id


@pytest.mark.django_db
def test_unknown_credential_type_falls_back_to_the_url_guesser(owner, team):
    """A hand-edited spreadsheet must not lose the whole row to a typo."""
    rows = "Acme WP,WordPres Admn,,https://acme.io/wp-admin,admin,pw,,\n"
    resp, data = _import(_client(owner), NATIVE_HEADER, rows)
    assert resp.status_code == 200, resp.content
    assert data["failed"] == 0, data
    assert Credential.objects.get(team=team, label="Acme WP").credential_type == "wordpress"


@pytest.mark.django_db
def test_credential_type_accepts_the_human_label(owner, team):
    rows = "Acme App,WordPress Application Password,,https://acme.io/,admin,pw,,\n"
    _import(_client(owner), NATIVE_HEADER, rows)
    cred = Credential.objects.get(team=team, label="Acme App")
    assert cred.credential_type == "wordpress_app_password"


@pytest.mark.django_db
def test_notes_column_is_read_when_present(owner, team):
    rows = "Acme WP,wordpress,,https://acme.io/wp-admin,admin,pw,Recovery email on file,\n"
    _import(_client(owner), NATIVE_HEADER, rows)
    assert Credential.objects.get(team=team, label="Acme WP").get_notes() == "Recovery email on file"


# ── LastPass fallback ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_lastpass_header_still_imports_with_extra_and_totp(owner, team):
    rows = 'https://acme.io/wp-admin,admin,pw,JBSWY3DPEHPK3PXP,"A note",Acme WP,Website Credentials,0\n'
    resp, data = _import(_client(owner), LASTPASS_HEADER, rows)
    assert resp.status_code == 200, resp.content
    assert data["created"] == 1, data

    cred = Credential.objects.get(team=team, label="Acme WP")
    assert cred.credential_type == "wordpress"
    notes = cred.get_notes()
    assert "A note" in notes
    # LastPass's totp column is now the credential's authenticator, not a note.
    assert cred.get_totp_secret() == "JBSWY3DPEHPK3PXP"
    assert "TOTP secret" not in notes


@pytest.mark.django_db
def test_unreadable_totp_is_kept_in_notes_not_dropped(owner, team):
    rows = 'https://acme.io/wp-admin,admin,pw,not!base32,,Acme WP,,0\n'
    _import(_client(owner), LASTPASS_HEADER, rows)
    cred = Credential.objects.get(team=team, label="Acme WP")
    assert not cred.has_totp
    assert "TOTP secret: not!base32" in cred.get_notes()


@pytest.mark.django_db
def test_department_and_totp_round_trip(owner, team):
    rows = "Acme GSC,google_search_console,,https://search.google.com,seo@x.io,pw,,,seo,JBSWY3DPEHPK3PXP\n"
    resp, data = _import(_client(owner), EXPORT_HEADER, rows)
    assert data["created"] == 1, data
    cred = Credential.objects.get(team=team, label="Acme GSC")
    assert cred.department == "seo"
    assert cred.get_totp_secret() == "JBSWY3DPEHPK3PXP"

    _, exported = _export_rows(_client(owner))
    row = next(r for r in exported if r["name"] == "Acme GSC")
    assert row["department"] == "seo"
    assert row["totp"] == "JBSWY3DPEHPK3PXP"


# ── The teams column ──────────────────────────────────────────────────────────


@pytest.fixture
def group(team):
    return SubTeam.objects.create(team=team, name="Web Team")


def _grant(group, credential, can_view=False):
    return SubTeamCredentialGrant.objects.create(
        sub_team=group,
        scope=SubTeamCredentialGrant.Scope.CREDENTIAL,
        credential=credential,
        can_view_password=can_view,
    )


@pytest.fixture
def granted_credential(owner, team, site, group):
    cred = CredentialService.create(
        label="Acme WP",
        credential_type="wordpress",
        login_url="https://acme.io/wp-admin",
        username="admin@acme.io",
        password="pw1",
        notes="",
        created_by=owner,
        team=team,
        website=site,
    )
    _grant(group, cred, can_view=True)
    return cred


@pytest.mark.django_db
def test_export_lists_the_groups_granted_this_credential(owner, granted_credential):
    _, rows = _export_rows(_client(owner))
    assert rows[0]["teams"] == "Web Team:view"


@pytest.mark.django_db
def test_export_omits_the_view_suffix_when_the_group_cannot_reveal(owner, team, group):
    cred = CredentialService.create(
        label="Acme WP", credential_type="wordpress", login_url="", username="a",
        password="p", notes="", created_by=owner, team=team, website=None,
    )
    _grant(group, cred, can_view=False)
    _, rows = _export_rows(_client(owner))
    assert rows[0]["teams"] == "Web Team"


@pytest.mark.django_db
def test_export_ignores_blanket_and_type_scoped_grants(owner, team, group, granted_credential):
    """Team-wide policy is not a property of a row and must not multiply into one."""
    SubTeamCredentialGrant.objects.create(
        sub_team=group, scope=SubTeamCredentialGrant.Scope.ALL
    )
    _, rows = _export_rows(_client(owner))
    assert rows[0]["teams"] == "Web Team:view"


@pytest.mark.django_db
def test_teams_column_creates_grants_on_import(owner, team, group):
    rows = "Acme WP,wordpress,,https://acme.io/wp-admin,admin,pw,,Web Team:view\n"
    resp, data = _import(_client(owner), NATIVE_HEADER, rows)
    assert resp.status_code == 200, resp.content
    assert data["grants_created"] == 1, data

    cred = Credential.objects.get(team=team, label="Acme WP")
    grant = SubTeamCredentialGrant.objects.get(sub_team=group, credential=cred)
    assert grant.scope == SubTeamCredentialGrant.Scope.CREDENTIAL
    assert grant.can_view_password is True


@pytest.mark.django_db
def test_teams_grant_defaults_to_no_password_reveal(owner, team, group):
    rows = "Acme WP,wordpress,,https://acme.io/wp-admin,admin,pw,,Web Team\n"
    _import(_client(owner), NATIVE_HEADER, rows)
    cred = Credential.objects.get(team=team, label="Acme WP")
    assert SubTeamCredentialGrant.objects.get(credential=cred).can_view_password is False


@pytest.mark.django_db
def test_groups_header_alias_is_accepted(owner, team, group):
    header = NATIVE_HEADER.replace(",teams", ",groups")
    rows = "Acme WP,wordpress,,https://acme.io/wp-admin,admin,pw,,Web Team\n"
    resp, data = _import(_client(owner), header, rows)
    assert resp.status_code == 200, resp.content
    assert data["grants_created"] == 1, data


@pytest.mark.django_db
def test_unknown_group_name_reports_an_error_and_still_imports_the_row(owner, team, group):
    rows = "Acme WP,wordpress,,https://acme.io/wp-admin,admin,pw,,Ghost Team\n"
    resp, data = _import(_client(owner), NATIVE_HEADER, rows)
    assert resp.status_code == 200, resp.content
    assert data["created"] == 1, data
    assert data["grants_created"] == 0, data
    assert any("Ghost Team" in e for e in data["errors"]), data
    assert Credential.objects.filter(team=team, label="Acme WP").exists()


@pytest.mark.django_db
def test_blank_teams_column_never_revokes_an_existing_grant(owner, team, group, granted_credential):
    """Revoking stays a deliberate act in the share dialog, not a CSV omission."""
    rows = "Acme WP,wordpress,acme.io,https://acme.io/wp-admin,admin@acme.io,pw1,,\n"
    resp, data = _import(_client(owner), NATIVE_HEADER, rows)
    assert resp.status_code == 200, resp.content
    assert data["updated"] == 1, data
    assert SubTeamCredentialGrant.objects.filter(credential=granted_credential).count() == 1


@pytest.mark.django_db
def test_reimporting_a_teams_value_does_not_duplicate_the_grant(owner, team, group, granted_credential):
    rows = "Acme WP,wordpress,acme.io,https://acme.io/wp-admin,admin@acme.io,pw1,,Web Team:view\n"
    c = _client(owner)
    _import(c, NATIVE_HEADER, rows)
    _import(c, NATIVE_HEADER, rows)
    assert SubTeamCredentialGrant.objects.filter(credential=granted_credential).count() == 1


# ── Role gating ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_manager_export_keeps_the_column_but_leaves_it_blank(
    owner, team, granted_credential
):
    """Export is manager-gated but group access is owner-only, so a manager gets
    the column present and empty rather than the access policy handed to them in
    a spreadsheet. The column stays so the file still round-trips."""
    manager = _member(team, "csv_manager@test.com", "manager")
    fields, rows = _export_rows(_client(manager))
    assert "teams" in fields
    assert rows[0]["teams"] == ""


@pytest.mark.django_db
def test_a_co_owner_export_includes_the_grants(owner, team, granted_credential):
    """The blanking branch reads the owner *role*, not `team.owner`, so a second
    owner exports the real policy."""
    co_owner = _member(team, "csv_co_owner@test.com", "owner")
    fields, rows = _export_rows(_client(co_owner))
    assert "teams" in fields
    assert rows[0]["teams"] != ""


@pytest.mark.django_db
def test_developer_cannot_export_at_all(owner, team, granted_credential):
    """Below manager the `teams` column never comes up, because the export
    endpoint itself is manager-gated (`RolePermission`, `required_role`).

    An export is a bulk reveal of every password in the vault, so that floor
    sits at the endpoint rather than on one column of it — which is why the
    blanking branch above is tested with a manager and not a developer.
    """
    developer = _member(team, "csv_dev@test.com", "developer")
    resp = _client(developer).get("/api/v1/credentials/export/")
    assert resp.status_code == 403, resp.content


@pytest.mark.django_db
def test_manager_import_ignores_teams_and_says_so(owner, team, group):
    """Counted and reported, never silently dropped: a permission change that
    did not happen must not look like one that did. The credentials themselves
    still land — only the grant column is refused."""
    manager = _member(team, "csv_manager2@test.com", "manager")
    rows = "Acme WP,wordpress,,https://acme.io/wp-admin,admin,pw,,Web Team:view\n"
    resp, data = _import(_client(manager), NATIVE_HEADER, rows)
    assert resp.status_code == 200, resp.content
    assert data["created"] == 1, data
    assert data["grants_created"] == 0, data
    assert data["grants_ignored"] == 1, data
    assert not SubTeamCredentialGrant.objects.exists()


@pytest.mark.django_db
def test_a_co_owner_import_applies_teams(owner, team, group):
    co_owner = _member(team, "csv_co_owner2@test.com", "owner")
    rows = "Acme WP,wordpress,,https://acme.io/wp-admin,admin,pw,,Web Team:view\n"
    resp, data = _import(_client(co_owner), NATIVE_HEADER, rows)
    assert resp.status_code == 200, resp.content
    assert data["created"] == 1, data
    assert data["grants_created"] == 1, data
    assert data["grants_ignored"] == 0, data
    assert SubTeamCredentialGrant.objects.exists()


@pytest.mark.django_db
def test_developer_cannot_import_at_all(owner, team, group):
    """Same floor on the way in: an import writes to the whole team's vault, so
    it is manager-gated at the endpoint.

    Nothing is written — not the credentials either, which is the part worth
    pinning: a refused import must not half-land.
    """
    developer = _member(team, "csv_dev2@test.com", "developer")
    rows = "Acme WP,wordpress,,https://acme.io/wp-admin,admin,pw,,Web Team:view\n"
    resp, _data = _import(_client(developer), NATIVE_HEADER, rows)
    assert resp.status_code == 403, resp.content
    assert not Credential.objects.exists()
    assert not SubTeamCredentialGrant.objects.exists()


# ── Preview ───────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_preview_writes_no_grants(owner, team, group):
    rows = "Acme WP,wordpress,,https://acme.io/wp-admin,admin,pw,,Web Team:view\n"
    resp, data = _import(_client(owner), NATIVE_HEADER, rows, mode="preview")
    assert resp.status_code == 200, resp.content
    assert data["created"] == 1, data
    assert not SubTeamCredentialGrant.objects.exists()
    assert not Credential.objects.exists()


# ── The shipped sample template ───────────────────────────────────────────────

SAMPLE_TSX = "frontend/src/components/credentials-vault-client.tsx"


def _shipped_sample_csv() -> str:
    """The `SAMPLE_CSV` constant the Sample button downloads.

    Read out of the frontend source rather than duplicated here: a template that
    drifts from the importer is worse than no template, since the one person who
    downloads it is the one who could not guess the columns.
    """
    import pathlib

    lines = pathlib.Path(SAMPLE_TSX).read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("const SAMPLE_CSV = ["))
    end = next(i for i, ln in enumerate(lines[start:], start) if ln.startswith("].join("))

    out = []
    for raw in lines[start + 1 : end]:
        entry = raw.strip().rstrip(",")
        if not entry or entry == '""':
            continue
        quote = entry[0]
        assert quote in "\"'", entry
        out.append(entry[1:-1].replace(f"\{quote}", quote))
    return "\n".join(out) + "\n"


@pytest.mark.django_db
def test_sample_template_header_matches_the_importer(owner, team):
    assert _shipped_sample_csv().splitlines()[0] == EXPORT_HEADER


@pytest.mark.django_db
def test_sample_template_imports_as_written(owner, team):
    Website.objects.create(team=team, name="Example", domain="example.com")
    sample = _shipped_sample_csv()

    resp = _client(owner).post(
        "/api/v1/credentials/import/",
        {"file": SimpleUploadedFile("sample.csv", sample.encode("utf-8"), content_type="text/csv")},
        format="multipart",
    )
    assert resp.status_code == 200, resp.content
    data = json.loads(resp.content)["data"]
    assert data["created"] == 4, data
    assert data["failed"] == 0, data
    assert data["errors"] == [], data

    gsc = Credential.objects.get(team=team, label="Example Co Search Console")
    assert gsc.folder.name == "SEO"
    assert Credential.objects.get(team=team, label="Example Co Website Login").folder.name == "Web"

    panel = Credential.objects.get(team=team, label="Example Co Hosting Panel")
    assert panel.credential_type == "siteground"
    assert panel.website.domain == "example.com"

    dns = Credential.objects.get(team=team, label="Cloudflare DNS")
    assert dns.credential_type == "cloudflare"
    assert dns.website_id is None
