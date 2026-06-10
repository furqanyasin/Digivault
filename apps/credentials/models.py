import hashlib

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.models import BaseModel
from apps.credentials import encryption


def score_password_strength(plaintext: str) -> int:
    """Heuristic password strength score 0–4 (no plaintext is stored).

    Computed at set-time so we never need to decrypt to assess strength.
    """
    if not plaintext:
        return 0
    score = 0
    if len(plaintext) >= 8:
        score += 1
    if len(plaintext) >= 12:
        score += 1
    if any(c.islower() for c in plaintext) and any(c.isupper() for c in plaintext):
        score += 1
    if any(c.isdigit() for c in plaintext):
        score += 1
    if any(not c.isalnum() for c in plaintext):
        score += 1
    return min(score, 4)


class CredentialQuerySet(models.QuerySet):
    def stale_passwords(self, older_than_days: int = 180):
        """Credentials whose password hasn't changed in `older_than_days`."""
        cutoff = timezone.now() - timezone.timedelta(days=older_than_days)
        return self.filter(last_password_changed_at__lt=cutoff)

    def visible_to(self, user):
        if user is None or not user.is_authenticated:
            return self.none()

        from apps.accounts.models import TeamMembership

        privileged_team_ids = TeamMembership.objects.filter(
            user=user,
            role__in=[TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER],
        ).values_list("team_id", flat=True)

        return self.filter(
            Q(team_id__in=privileged_team_ids)
            | Q(created_by=user)
            | Q(shares__user=user)
        ).distinct()


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

    team = models.ForeignKey(
        "accounts.Team",
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    website = models.ForeignKey(
        "websites.Website",
        on_delete=models.SET_NULL,
        related_name="credentials",
        null=True,
        blank=True,
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

    # Password health (auto-maintained by set_password)
    last_password_changed_at = models.DateTimeField(null=True, blank=True)
    password_strength = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["credential_type", "label"]
        indexes = [
            models.Index(fields=["team", "credential_type"], name="credentials_team_type_idx"),
        ]

    objects = CredentialQuerySet.as_manager()

    def __str__(self) -> str:
        site = self.website or "standalone"
        return f"{self.label} ({self.credential_type}) — {site}"

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
        self.last_password_changed_at = timezone.now()
        self.password_strength = score_password_strength(plaintext)

    @property
    def password_age_days(self) -> int | None:
        if not self.last_password_changed_at:
            return None
        return (timezone.now() - self.last_password_changed_at).days

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


class CredentialShare(BaseModel):
    """Grants a developer view+reveal access to a single credential.

    Owners and managers do not need rows here — their access is implicit
    via role.  A creator also does not need a row.  Modification of the
    credential remains gated by `can_modify_credential`.
    """

    credential = models.ForeignKey(
        Credential, on_delete=models.CASCADE, related_name="shares"
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="credential_shares",
    )
    shared_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credential_shares_granted",
    )
    # When False, the recipient can use the credential (e.g. extension autofill)
    # but the dashboard never shows them the plaintext password.
    can_view_password = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["credential", "user"],
                name="credentialshare_unique_per_user",
            )
        ]
        indexes = [models.Index(fields=["user", "credential"])]

    def __str__(self) -> str:
        return f"{self.credential.label} → {self.user.email}"
