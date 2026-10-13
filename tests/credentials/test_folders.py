"""User-made folders, shared with groups — the LastPass shared-folder model.

Folders replaced department tags as the way a team arranges the vault and
gives a group access to a set of logins.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamMembership, User
from apps.accounts.services import TeamService
from apps.credentials.models import Credential, SubTeamCredentialGrant, VaultFolder
from apps.credentials.services import CredentialService

PW = "Pass123!"


def _client_for(user):
    c = APIClient()
    resp = c.post("/api/v1/auth/token/", {"email": user.email, "password": PW}, format="json")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="vf_owner@test.com", password=PW)


@pytest.fixture
def team(owner):
    return TeamService.create(name="VF Agency", owner=owner)


@pytest.fixture
def member(team):
    def make(email, role=TeamMembership.Role.DEVELOPER, group=None):
        u = User.objects.create_user(email=email, password=PW)
        TeamMembership.objects.create(user=u, team=team, role=role, sub_team=group)
        u.active_team = team
        u.save(update_fields=["active_team"])
        return u

    return make


def _cred(team, owner, **kw):
    defaults = dict(
        team=team, label="Login", credential_type="custom", login_url="",
        username="u", password="s3", notes="", created_by=owner,
    )
    defaults.update(kw)
    return CredentialService.create(**defaults)


@pytest.mark.django_db
class TestFolderCrud:
    def test_manager_creates_renames_deletes(self, owner, team):
        c = _client_for(owner)
        created = c.post("/api/v1/credentials/folders/", {"name": "SEO"}, format="json")
        assert created.status_code == 201, created.data
        fid = created.data["id"]

        dup = c.post("/api/v1/credentials/folders/", {"name": "seo"}, format="json")
        assert dup.status_code == 400

        renamed = c.patch(f"/api/v1/credentials/folders/{fid}/", {"name": "SEO tools"}, format="json")
        assert renamed.data["name"] == "SEO tools"

        cred = _cred(team, owner, folder=VaultFolder.objects.get(pk=fid))
        assert c.delete(f"/api/v1/credentials/folders/{fid}/").status_code == 204
        cred.refresh_from_db()
        assert cred.folder_id is None  # unfiled, not deleted

    def test_developer_cannot_create(self, member):
        dev = member("dev@vf.io")
        assert _client_for(dev).post(
            "/api/v1/credentials/folders/", {"name": "Mine"}, format="json"
        ).status_code == 403

    def test_list_counts_only_what_you_can_see(self, owner, team, member):
        folder = VaultFolder.objects.create(team=team, name="Web")
        _cred(team, owner, folder=folder)
        _cred(team, owner, folder=folder)
        dev = member("dev@vf.io")
        rows = _client_for(dev).get("/api/v1/credentials/folders/").data
        assert [(r["name"], r["credential_count"], r["groups"]) for r in rows] == [("Web", 0, None)]
        owner_rows = _client_for(owner).get("/api/v1/credentials/folders/").data
        assert owner_rows[0]["credential_count"] == 2
        assert owner_rows[0]["groups"] == []


@pytest.mark.django_db
class TestFiling:
    def test_create_and_move_by_folder_id(self, owner, team):
        a = VaultFolder.objects.create(team=team, name="SEO")
        b = VaultFolder.objects.create(team=team, name="Web")
        c = _client_for(owner)
        resp = c.post("/api/v1/credentials/", {
            "label": "GSC", "credential_type": "google_search_console", "folder_id": str(a.pk),
        }, format="json")
        assert resp.data["folder_name"] == "SEO"
        moved = c.patch(f"/api/v1/credentials/{resp.data['id']}/", {"folder_id": str(b.pk)}, format="json")
        assert moved.data["folder_name"] == "Web"
        unfiled = c.patch(f"/api/v1/credentials/{resp.data['id']}/", {"folder_id": None}, format="json")
        assert unfiled.data["folder_id"] is None

    def test_other_teams_folder_refused(self, owner, team):
        other = TeamService.create(name="Other", owner=User.objects.create_user(email="o@vf.io", password=PW))
        theirs = VaultFolder.objects.create(team=other, name="Theirs")
        resp = _client_for(owner).post("/api/v1/credentials/", {
            "label": "x", "credential_type": "custom", "folder_id": str(theirs.pk),
        }, format="json")
        assert resp.status_code == 400

    def test_client_follows_the_website(self, owner, team):
        from apps.clients.models import Client
        from apps.websites.models import Website

        acme = Client.objects.create(team=team, name="Acme")
        site = Website.objects.create(team=team, name="Acme", domain="acme.io", client=acme)
        cred = _cred(team, owner)
        _client_for(owner).patch(f"/api/v1/credentials/{cred.pk}/", {"website_id": str(site.pk)}, format="json")
        cred.refresh_from_db()
        assert cred.client_id == acme.pk


@pytest.mark.django_db
class TestSharedFolders:
    def _share(self, owner, group, folder, can_view=False):
        return _client_for(owner).post(
            f"/api/v1/sub-teams/{group.pk}/credential-grants/",
            {"scope": "folder", "folder": str(folder.pk), "can_view_password": can_view},
            format="json",
        )

    def test_group_sees_the_folder_use_only(self, owner, team, member):
        folder = VaultFolder.objects.create(team=team, name="SEO")
        inside = _cred(team, owner, folder=folder)
        outside = _cred(team, owner)
        group = SubTeam.objects.create(team=team, name="SEO Team")
        seo = member("seo@vf.io", role=TeamMembership.Role.SEO_EXECUTIVE, group=group)
        resp = self._share(owner, group, folder)
        assert resp.status_code == 201, resp.data
        assert resp.data["folder_name"] == "SEO"

        visible = set(Credential.objects.visible_to(seo).values_list("pk", flat=True))
        assert visible == {inside.pk}
        assert outside.pk not in visible
        revealed = _client_for(seo).post(f"/api/v1/credentials/{inside.pk}/reveal/").data
        assert revealed["password_hidden"] is True

        # Filed later -> covered too.
        later = _cred(team, owner, folder=folder)
        assert Credential.objects.visible_to(seo).filter(pk=later.pk).exists()

    def test_can_view_password(self, owner, team, member):
        folder = VaultFolder.objects.create(team=team, name="SEO")
        inside = _cred(team, owner, folder=folder, password="s3")
        group = SubTeam.objects.create(team=team, name="SEO Team")
        seo = member("seo@vf.io", group=group)
        self._share(owner, group, folder, can_view=True)
        assert _client_for(seo).post(f"/api/v1/credentials/{inside.pk}/reveal/").data["password"] == "s3"

    def test_other_teams_folder_cannot_be_granted(self, owner, team):
        other = TeamService.create(name="Other", owner=User.objects.create_user(email="o@vf.io", password=PW))
        theirs = VaultFolder.objects.create(team=other, name="Theirs")
        group = SubTeam.objects.create(team=team, name="SEO Team")
        assert self._share(owner, group, theirs).status_code == 400

    def test_deleting_folder_ends_access(self, owner, team, member):
        folder = VaultFolder.objects.create(team=team, name="SEO")
        cred = _cred(team, owner, folder=folder)
        group = SubTeam.objects.create(team=team, name="SEO Team")
        seo = member("seo@vf.io", group=group)
        self._share(owner, group, folder)
        folder.delete()
        assert not Credential.objects.visible_to(seo).filter(pk=cred.pk).exists()
        assert not SubTeamCredentialGrant.objects.filter(sub_team=group).exists()


@pytest.mark.django_db
def test_lastpass_grouping_becomes_a_folder(owner, team):
    from django.core.files.uploadedfile import SimpleUploadedFile

    csv = (
        "url,username,password,totp,extra,name,grouping,fav\n"
        "https://app.semrush.com,seo@x.io,pw,,,Semrush,SEO\\Tools,0\n"
        "https://acme.io/wp-admin,admin,pw,,,Acme WP,Website Credentials,0\n"
    )
    _client_for(owner).post(
        "/api/v1/credentials/import/",
        {"file": SimpleUploadedFile("lp.csv", csv.encode(), content_type="text/csv")},
        format="multipart",
    )
    semrush = Credential.objects.get(team=team, label="Semrush")
    assert semrush.folder.name == "SEO / Tools"
    # The vault's own section names are not folders.
    assert Credential.objects.get(team=team, label="Acme WP").folder_id is None


@pytest.mark.django_db
def test_department_access_migrates_to_a_folder_grant(owner, team, member):
    """The data migration keeps exactly the access a department tag gave."""
    from importlib import import_module

    from django.apps import apps as django_apps

    group = SubTeam.objects.create(
        team=team, name="SEO Team", department="seo", department_can_view_password=True
    )
    seo_cred = _cred(team, owner, credential_type="google_search_console")
    dev_cred = _cred(team, owner, credential_type="cpanel")
    import_module(
        "apps.credentials.migrations.0017_department_access_to_folders"
    ).forwards(django_apps, None)

    seo_cred.refresh_from_db()
    dev_cred.refresh_from_db()
    assert seo_cred.folder.name == "SEO"
    assert dev_cred.folder_id is None  # nobody had dev access: no folder invented
    grant = SubTeamCredentialGrant.objects.get(sub_team=group)
    assert (grant.scope, grant.folder_id, grant.can_view_password) == ("folder", seo_cred.folder_id, True)
    group.refresh_from_db()
    assert group.department == ""


@pytest.mark.django_db
class TestSaveCheck:
    def _check(self, user, password, username="admin", domain="acme.io"):
        return _client_for(user).post(
            "/api/extension/credentials/check/",
            {"domain": domain, "username": username, "password": password}, format="json",
        ).data["status"]

    def test_statuses(self, owner, team, member):
        from apps.websites.models import Website

        site = Website.objects.create(team=team, name="Acme", domain="acme.io")
        _cred(team, owner, website=site, username="admin", password="same-pw")
        assert self._check(owner, "same-pw") == "same"
        assert self._check(owner, "other-pw") == "changed"
        assert self._check(owner, "x", username="someone-else") == "new"
        dev = member("dev@vf.io")
        assert self._check(dev, "other-pw") == "readonly"


@pytest.mark.django_db
class TestFolderSharedWithPeople:
    def _share(self, by, folder, *users, can_view=None):
        body = {"user_ids": [str(u.pk) for u in users]}
        if can_view is not None:
            body["can_view_password"] = can_view
        return _client_for(by).post(f"/api/v1/credentials/folders/{folder.pk}/members/", body, format="json")

    def test_whole_folder_in_one_step_password_hidden(self, owner, team, member):
        folder = VaultFolder.objects.create(team=team, name="SEO")
        logins = [_cred(team, owner, folder=folder, label=f"Site {i}") for i in range(5)]
        outside = _cred(team, owner)
        amar = member("amar@vf.io", role=TeamMembership.Role.SEO_EXECUTIVE)

        resp = self._share(owner, folder, amar)
        assert resp.status_code == 200, resp.data
        visible = set(Credential.objects.visible_to(amar).values_list("pk", flat=True))
        assert visible == {c.pk for c in logins}
        assert outside.pk not in visible
        # Hidden unless asked.
        assert _client_for(amar).post(f"/api/v1/credentials/{logins[0].pk}/reveal/").data["password_hidden"] is True
        # Filed later reaches him too.
        later = _cred(team, owner, folder=folder)
        assert Credential.objects.visible_to(amar).filter(pk=later.pk).exists()

    def test_can_view_and_reshare_updates_it(self, owner, team, member):
        folder = VaultFolder.objects.create(team=team, name="SEO")
        cred = _cred(team, owner, folder=folder, password="s3")
        amar = member("amar@vf.io")
        self._share(owner, folder, amar, can_view=True)
        assert _client_for(amar).post(f"/api/v1/credentials/{cred.pk}/reveal/").data["password"] == "s3"
        self._share(owner, folder, amar, can_view=False)
        assert _client_for(amar).post(f"/api/v1/credentials/{cred.pk}/reveal/").data["password_hidden"] is True

    def test_remove_ends_access(self, owner, team, member):
        folder = VaultFolder.objects.create(team=team, name="SEO")
        cred = _cred(team, owner, folder=folder)
        amar = member("amar@vf.io")
        self._share(owner, folder, amar)
        resp = _client_for(owner).delete(f"/api/v1/credentials/folders/{folder.pk}/members/{amar.pk}/")
        assert resp.status_code == 204
        assert not Credential.objects.visible_to(amar).filter(pk=cred.pk).exists()

    def test_members_listed_for_managers_only(self, owner, team, member):
        folder = VaultFolder.objects.create(team=team, name="SEO")
        amar = member("amar@vf.io")
        self._share(owner, folder, amar)
        rows = _client_for(owner).get("/api/v1/credentials/folders/").data
        assert [m["email"] for m in rows[0]["members"]] == [amar.email]
        assert _client_for(amar).get("/api/v1/credentials/folders/").data[0]["members"] is None

    def test_developer_cannot_share_a_folder(self, owner, team, member):
        folder = VaultFolder.objects.create(team=team, name="SEO")
        dev, other = member("dev@vf.io"), member("other@vf.io")
        assert self._share(dev, folder, other).status_code == 403

    def test_who_has_access_and_handover(self, owner, team, member):
        folder = VaultFolder.objects.create(team=team, name="SEO")
        cred = _cred(team, owner, folder=folder)
        amar, heir = member("amar@vf.io"), member("heir@vf.io")
        self._share(owner, folder, amar)
        rows = {r["email"]: r for r in _client_for(owner).get(f"/api/v1/credentials/{cred.pk}/access/").data}
        assert rows[amar.email]["routes"][0]["kind"] == "folder"
        _client_for(owner).post(
            f"/api/v1/credentials/members/{amar.pk}/handover/",
            {"to_user_id": str(heir.pk), "revoke_shares": True}, format="json",
        )
        assert not Credential.objects.visible_to(amar).exists()
