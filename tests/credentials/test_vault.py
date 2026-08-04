import pytest

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.common.exceptions import ForbiddenError
from apps.credentials.encryption import decrypt, encrypt
from apps.credentials.models import Credential
from apps.credentials.services import CredentialService
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="cv_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Vault Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Vault Site", domain="vault.io")


@pytest.fixture
def viewer(db, team):
    u = User.objects.create_user(email="viewer@test.com", password="Pass123!")
    TeamMembership.objects.create(user=u, team=team, role=TeamMembership.Role.VIEWER)
    u.active_team = team
    u.save()
    return u


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        plaintext = "super-secret-password-123"
        ciphertext = encrypt(plaintext)
        assert ciphertext != plaintext.encode()
        assert decrypt(ciphertext) == plaintext

    def test_empty_string_roundtrip(self):
        assert decrypt(encrypt("")) == ""

    def test_encrypt_returns_bytes(self):
        assert isinstance(encrypt("hello"), bytes)

    def test_different_calls_produce_different_ciphertext(self):
        # Fernet uses a random IV — same plaintext yields different ciphertext
        c1 = encrypt("same")
        c2 = encrypt("same")
        assert c1 != c2
        assert decrypt(c1) == decrypt(c2) == "same"


@pytest.mark.django_db
class TestCredentialModel:
    def test_set_get_username(self, website, owner):
        cred = Credential(team=website.team, website=website, label="WP", credential_type="wordpress")
        cred.set_username("admin")
        cred.set_password("hunter2")
        cred.set_notes("Main WP site")
        cred.save()

        cred.refresh_from_db()
        assert cred.get_username() == "admin"
        assert cred.get_password() == "hunter2"
        assert cred.get_notes() == "Main WP site"

    def test_raw_db_field_is_not_plaintext(self, website, owner):
        cred = Credential(team=website.team, website=website, label="FTP", credential_type="ftp")
        cred.set_password("plainpassword")
        cred.save()
        cred.refresh_from_db()
        assert b"plainpassword" not in bytes(cred._password)


@pytest.mark.django_db
class TestCredentialService:
    def test_create_and_reveal(self, website, owner):
        owner.active_team = website.team
        owner.save()
        cred = CredentialService.create(
            website=website,
            label="GoDaddy",
            credential_type="godaddy",
            login_url="https://sso.godaddy.com",
            username="myuser",
            password="mypass",
            notes="Main registrar",
            created_by=owner,
        )
        revealed = CredentialService.reveal(cred, owner)
        assert revealed["username"] == "myuser"
        assert revealed["password"] == "mypass"
        assert revealed["notes"] == "Main registrar"

    def test_viewer_cannot_reveal(self, website, viewer):
        cred = CredentialService.create(
            website=website,
            label="cPanel",
            credential_type="cpanel",
            login_url="",
            username="u",
            password="p",
            notes="",
            created_by=viewer,
        )
        with pytest.raises(ForbiddenError):
            CredentialService.reveal(cred, viewer)

    def test_reveal_logs_access(self, website, owner):
        owner.active_team = website.team
        owner.save()
        cred = CredentialService.create(
            website=website, label="CF", credential_type="cloudflare",
            login_url="", username="u", password="p", notes="", created_by=owner,
        )
        CredentialService.reveal(cred, owner)
        assert cred.access_logs.filter(action="viewed").exists()

    def test_update_credential(self, website, owner):
        owner.active_team = website.team
        owner.save()
        cred = CredentialService.create(
            website=website, label="Old", credential_type="wordpress",
            login_url="", username="old_u", password="old_p", notes="", created_by=owner,
        )
        CredentialService.update(cred, username="new_u", password="new_p", updated_by=owner)
        revealed = CredentialService.reveal(cred, owner)
        assert revealed["username"] == "new_u"
        assert revealed["password"] == "new_p"


@pytest.mark.django_db
class TestCredentialAPI:
    def _client(self, user):
        from rest_framework.test import APIClient
        c = APIClient()
        resp = c.post(
            "/api/v1/auth/token/",
            {"email": user.email, "password": "Pass123!"},
            format="json",
        )
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        return c

    def test_create_and_list(self, website, owner):
        client = self._client(owner)
        resp = client.post(
            f"/api/v1/websites/{website.pk}/credentials/",
            {
                "label": "WordPress Admin",
                "credential_type": "wordpress",
                "login_url": "https://vault.io/wp-admin",
                "username": "admin",
                "password": "secret",
                "notes": "",
            },
            format="json",
        )
        assert resp.status_code == 201

        list_resp = client.get(f"/api/v1/websites/{website.pk}/credentials/")
        assert list_resp.status_code == 200
        labels = [c["label"] for c in list_resp.data]
        assert "WordPress Admin" in labels

    def test_list_response_has_no_password_field(self, website, owner):
        CredentialService.create(
            website=website, label="Safe", credential_type="ftp",
            login_url="", username="u", password="secret_pw", notes="", created_by=owner,
        )
        client = self._client(owner)
        resp = client.get(f"/api/v1/websites/{website.pk}/credentials/")
        for item in resp.data:
            assert "password" not in item
            assert "_password" not in item

    def test_reveal_returns_plaintext(self, website, owner):
        cred = CredentialService.create(
            website=website, label="Rev", credential_type="cpanel",
            login_url="", username="revuser", password="revpass", notes="n", created_by=owner,
        )
        client = self._client(owner)
        resp = client.post(f"/api/v1/credentials/{cred.pk}/reveal/")
        assert resp.status_code == 200
        assert resp.data["password"] == "revpass"
