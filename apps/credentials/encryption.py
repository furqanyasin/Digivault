"""Fernet AES-256 encryption helpers for the credential vault.

The encryption key lives exclusively in the VAULT_ENCRYPTION_KEY environment
variable — never in the database or logs.  All encrypt/decrypt operations go
through this module so the key reference stays in one place.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _get_fernet() -> Fernet:
    key: str = settings.VAULT_ENCRYPTION_KEY
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt(plaintext: str) -> bytes:
    """Return Fernet-encrypted ciphertext bytes for a plaintext string."""
    if not plaintext:
        return b""
    return _get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    """Decrypt Fernet ciphertext and return the plaintext string.

    Raises ``InvalidToken`` if the ciphertext is tampered or the key is wrong.
    Callers should catch this and treat it as a vault integrity error.
    """
    if not ciphertext:
        return ""
    return _get_fernet().decrypt(ciphertext).decode("utf-8")


def rotate_key(old_key: bytes, new_key: bytes, ciphertext: bytes) -> bytes:
    """Re-encrypt a single ciphertext under a new key.

    Used during quarterly key rotation — called per-credential by the
    management command, not by application request paths.
    """
    plaintext = Fernet(old_key).decrypt(ciphertext)
    return Fernet(new_key).encrypt(plaintext)
