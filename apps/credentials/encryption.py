"""Fernet AES-256 encryption helpers for the credential vault.

Encryption keys live exclusively in environment variables — never in the
database or logs.  All encrypt/decrypt operations go through this module so the
key reference stays in one place.

Key rotation is supported via ``MultiFernet``:

  * ``VAULT_ENCRYPTION_KEYS`` — comma-separated, ordered list of Fernet keys.
    The **first** key encrypts new data; **all** keys are tried on decryption.
    To rotate: prepend a new key, deploy, run ``rotate_vault_keys`` to
    re-encrypt existing blobs under the new primary, then drop the old key.
  * ``VAULT_ENCRYPTION_KEY`` — legacy single key. Still honored when
    ``VAULT_ENCRYPTION_KEYS`` is unset, so existing deployments keep working.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

__all__ = ["encrypt", "decrypt", "rotate_token", "rotate_key", "InvalidToken"]


def _get_keys() -> list[bytes]:
    """Return the ordered list of vault keys as bytes (primary first)."""
    keys = getattr(settings, "VAULT_ENCRYPTION_KEYS", None) or []
    if not keys:
        single = getattr(settings, "VAULT_ENCRYPTION_KEY", "") or ""
        keys = [single] if single else []
    if not keys:
        raise ValueError(
            "No vault key configured. Set VAULT_ENCRYPTION_KEYS or VAULT_ENCRYPTION_KEY."
        )
    return [k.encode() if isinstance(k, str) else k for k in keys]


def _get_multifernet() -> MultiFernet:
    return MultiFernet([Fernet(k) for k in _get_keys()])


def encrypt(plaintext: str) -> bytes:
    """Return ciphertext bytes for a plaintext string, encrypted under the primary key."""
    if not plaintext:
        return b""
    return _get_multifernet().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    """Decrypt ciphertext (trying every configured key) and return the plaintext.

    Raises ``InvalidToken`` if the ciphertext is tampered or no key matches.
    Callers should catch this and treat it as a vault integrity error.
    """
    if not ciphertext:
        return ""
    return _get_multifernet().decrypt(ciphertext).decode("utf-8")


def rotate_token(ciphertext: bytes) -> bytes:
    """Re-encrypt a ciphertext under the current primary key (MultiFernet.rotate).

    Decrypts with whichever existing key matches, then re-encrypts with the
    primary. Used by the ``rotate_vault_keys`` management command.
    """
    if not ciphertext:
        return b""
    return _get_multifernet().rotate(ciphertext)


def rotate_key(old_key: bytes, new_key: bytes, ciphertext: bytes) -> bytes:
    """Re-encrypt a single ciphertext from one explicit key to another.

    Retained for backward compatibility; new code should prefer ``rotate_token``
    which uses the configured key list.
    """
    plaintext = Fernet(old_key).decrypt(ciphertext)
    return Fernet(new_key).encrypt(plaintext)
