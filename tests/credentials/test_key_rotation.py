"""Phase 0.4 — MultiFernet key rotation."""

import pytest
from cryptography.fernet import Fernet, InvalidToken
from django.core.management import call_command
from django.test import override_settings

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.credentials import encryption
from apps.credentials.models import Credential

KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="owner@rotate.com", password="SecurePass1!")
    return TeamService.create(name="Rotate Team", owner=owner)


@override_settings(VAULT_ENCRYPTION_KEYS=[KEY_A])
def test_roundtrip_single_key():
    token = encryption.encrypt("hunter2")
    assert encryption.decrypt(token) == "hunter2"


def test_old_ciphertext_decrypts_after_adding_new_primary():
    # Encrypt under A only...
    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_A]):
        token = encryption.encrypt("secretpw")
    # ...then add B as the new primary; A still present for decryption.
    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_B, KEY_A]):
        assert encryption.decrypt(token) == "secretpw"


def test_encrypt_uses_primary_key():
    # With [B, A], new data must be encrypted under B.
    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_B, KEY_A]):
        token = encryption.encrypt("newdata")
    # B alone can decrypt it; A alone cannot.
    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_B]):
        assert encryption.decrypt(token) == "newdata"
    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_A]):
        with pytest.raises(InvalidToken):
            encryption.decrypt(token)


@pytest.mark.django_db
def test_rotate_vault_keys_reencrypts_under_new_primary(team):
    # Create a credential encrypted under A.
    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_A]):
        cred = Credential(team=team, label="WP Admin")
        cred.set_username("admin")
        cred.set_password("p@ss")
        cred.set_notes("root login")
        cred.save()

    # Rotate: B is now primary, A still available to decrypt old blobs.
    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_B, KEY_A]):
        call_command("rotate_vault_keys")

    # After rotation, B alone must decrypt everything (A can be retired).
    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_B]):
        cred.refresh_from_db()
        assert cred.get_username() == "admin"
        assert cred.get_password() == "p@ss"
        assert cred.get_notes() == "root login"


@pytest.mark.django_db
def test_dry_run_does_not_change_data(team):
    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_A]):
        cred = Credential(team=team, label="X")
        cred.set_password("orig")
        cred.save()
        original_blob = bytes(cred._password)

    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_B, KEY_A]):
        call_command("rotate_vault_keys", "--dry-run")

    cred.refresh_from_db()
    assert bytes(cred._password) == original_blob


def test_wrong_key_raises_invalid_token():
    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_A]):
        token = encryption.encrypt("data")
    with override_settings(VAULT_ENCRYPTION_KEYS=[KEY_B]):
        with pytest.raises(InvalidToken):
            encryption.decrypt(token)


def test_legacy_single_key_still_works():
    with override_settings(VAULT_ENCRYPTION_KEYS=[], VAULT_ENCRYPTION_KEY=KEY_A):
        token = encryption.encrypt("legacy")
        assert encryption.decrypt(token) == "legacy"
