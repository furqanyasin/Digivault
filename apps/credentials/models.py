import hashlib

from django.db import models

from apps.common.models import BaseModel
from apps.credentials import encryption


class Credential(BaseModel):
    """Encrypted login credential for a client website resource.

    Usernames, passwords, and notes are stored as Fernet-encrypted binary
    fields.  Plain values are never stored; even the DB column type (BinaryField)
    signals to operators that these are ciphertext blobs, not readable strings.

    The model exposes set_*/get_* pairs to keep encryption transparent to callers.
    """

    class CredentialType(models.TextChoices):
        WORDPRESS = "wordpress", "WordPress Admin"
        CPANEL = "cpanel", "cPanel"
        GODADDY = "godaddy", "GoDaddy"
        NAMECHEAP = "namecheap", "Namecheap"
        HOSTINGER = "hostinger", "Hostinger"
        CLOUDFLARE = "cloudflare", "Cloudflare"
        FTP = "ftp", "FTP / SFTP"
        WIX = "wix", "Wix"
        WEBFLOW = "webflow", "Webflow"
        FRAMER = "framer", "Framer"
        SHOPIFY = "shopify", "Shopify"
        SITEGROUND = "siteground", "SiteGround"
        BLUEHOST = "bluehost", "Bluehost"
        WPENGINE = "wpengine", "WP Engine"
        KINSTA = "kinsta", "Kinsta"
        CUSTOM = "custom", "Custom"

    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    label = models.CharField(max_length=200)
    credential_type = models.CharField(
        max_length=30, choices=CredentialType.choices, default=CredentialType.CUSTOM
    )
    login_url = models.URLField(max_length=500, blank=True)

    # Encrypted binary fields — never contain plaintext
    _username = models.BinaryField(blank=True, editable=False)
    _password = models.BinaryField(blank=True, editable=False)
    _notes = models.BinaryField(blank=True, editable=False)
    # SHA-256 hash of username for fast duplicate lookup (no decryption required)
    username_hash = models.CharField(max_length=64, blank=True, db_index=True)

    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_credentials",
    )

    class Meta:
        ordering = ["credential_type", "label"]
        indexes = [
            models.Index(fields=["website", "credential_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.credential_type}) — {self.website}"

    # ------------------------------------------------------------------
    # Encrypted field accessors
    # ------------------------------------------------------------------

    @staticmethod
    def hash_username(plaintext: str) -> str:
        return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()

    def set_username(self, plaintext: str) -> None:
        self._username = encryption.encrypt(plaintext)
        self.username_hash = self.hash_username(plaintext)

    def get_username(self) -> str:
        return encryption.decrypt(bytes(self._username)) if self._username else ""

    def set_password(self, plaintext: str) -> None:
        self._password = encryption.encrypt(plaintext)

    def get_password(self) -> str:
        return encryption.decrypt(bytes(self._password)) if self._password else ""

    def set_notes(self, plaintext: str) -> None:
        self._notes = encryption.encrypt(plaintext)

    def get_notes(self) -> str:
        return encryption.decrypt(bytes(self._notes)) if self._notes else ""


class CredentialAccessLog(BaseModel):
    """Immutable audit record of every credential reveal or copy event.

    Written by the reveal API endpoint.  Application code must never DELETE
    or UPDATE these rows — the DB user used by the app should only have INSERT
    on this table in production.
    """

    class Action(models.TextChoices):
        VIEWED = "viewed", "Viewed"
        COPIED_PASSWORD = "copied_password", "Copied Password"
        EDITED = "edited", "Edited"

    credential = models.ForeignKey(
        Credential,
        on_delete=models.CASCADE,
        related_name="access_logs",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="credential_access_logs",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["credential", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} {self.action} '{self.credential.label}'"
