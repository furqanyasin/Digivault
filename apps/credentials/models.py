import hashlib
from urllib.parse import parse_qs, urlparse

import pyotp
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
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


def normalize_totp_secret(value: str) -> str:
    """The base32 secret in `value`, or "" for blank. Raises ValueError.

    Accepts what people actually paste: the bare secret LastPass and most
    sites show (often grouped in fours, lower-case), or the whole
    `otpauth://totp/...?secret=...` URI a QR code encodes. Only the secret is
    kept — issuer and account label are already the credential's own label and
    username, and a second copy of them inside a ciphertext would drift.
    Non-default digits/period/algorithm are refused rather than silently
    producing codes the site will reject.
    """
    value = (value or "").strip()
    if not value:
        return ""
    if value.lower().startswith("otpauth://"):
        parsed = urlparse(value)
        if parsed.netloc.lower() != "totp":
            raise ValueError("Only time-based (TOTP) codes are supported.")
        params = {k.lower(): v[0] for k, v in parse_qs(parsed.query).items()}
        if params.get("digits", "6") != "6" or params.get("period", "30") != "30" or (
            params.get("algorithm", "SHA1").upper() != "SHA1"
        ):
            raise ValueError("Only 6-digit, 30-second SHA1 codes are supported.")
        value = params.get("secret", "")
    secret = "".join(value.split()).replace("-", "").upper().rstrip("=")
    if not secret:
        raise ValueError("No secret found.")
    try:
        pyotp.TOTP(secret).now()
    except Exception as exc:  # binascii.Error, TypeError — not base32
        raise ValueError("That is not a valid authenticator secret.") from exc
    return secret


class CredentialQuerySet(models.QuerySet):
    def visible_to(self, user):
        if user is None or not user.is_authenticated:
            return self.none()

        from apps.accounts.models import TeamMembership

        privileged_team_ids = TeamMembership.objects.filter(
            user=user,
            role__in=[TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER],
        ).values_list("team_id", flat=True)

        # Shares through a subquery of *active* rows: a temporary share from an
        # approved access request stops granting anything the moment it
        # expires, whether or not the nightly purge has deleted it yet.
        access = (
            Q(team_id__in=privileged_team_ids)
            | Q(created_by=user)
            | Q(pk__in=CredentialShare.objects.active().filter(user=user).values("credential_id"))
            # A folder shared with this person: everything filed in it.
            | Q(folder_id__in=FolderShare.objects.filter(user=user).values("folder_id"))
        )
        group_access = self._group_grant_q(user)
        if group_access is not None:
            access |= group_access
        return self.filter(access).distinct()

    @staticmethod
    def _group_grant_q(user):
        """Q matching the credentials this user's group has been granted.

        Returns None when the user is in no group, or their group holds no
        grants, so the caller leaves the filter untouched rather than OR-ing an
        empty Q (which matches everything).

        Two small indexed reads feed the Q instead of one nested subquery.
        `visible_to` is the only gate in front of the entire vault, so
        readability here is worth the extra query.
        """
        from apps.accounts.models import TeamMembership

        sub_team_ids = list(
            TeamMembership.objects.filter(user=user)
            .exclude(sub_team_id=None)
            .values_list("sub_team_id", flat=True)
        )
        if not sub_team_ids:
            return None

        grants = SubTeamCredentialGrant.objects.filter(
            sub_team_id__in=sub_team_ids
        ).values_list(
            "scope", "credential_type", "credential_id", "folder_id", "sub_team__team_id"
        )

        q = Q()
        matched = False
        for scope, credential_type, credential_id, folder_id, team_id in grants:
            if scope == SubTeamCredentialGrant.Scope.ALL:
                q |= Q(team_id=team_id)
            elif scope == SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE:
                q |= Q(team_id=team_id, credential_type=credential_type)
            elif scope == SubTeamCredentialGrant.Scope.CREDENTIAL:
                # Scoped by pk, and the model's clean() already refuses a
                # credential from another team.
                q |= Q(pk=credential_id)
            elif scope == SubTeamCredentialGrant.Scope.FOLDER:
                # A shared folder: everything filed in it, now or later.
                q |= Q(team_id=team_id, folder_id=folder_id)
            else:
                # An unknown scope grants nothing. Fail closed.
                continue
            matched = True
        return q if matched else None


class VaultFolder(BaseModel):
    """A folder the team makes for itself — "SEO", "Web", "Agency tools".

    The LastPass model: folders are named and arranged by people, not derived
    from clients (the website already says which client a login is for). A
    folder is also the unit of group access: a `SubTeamCredentialGrant` with
    scope FOLDER shows a group everything filed in it, including what is filed
    there later — LastPass's shared folder.
    """

    team = models.ForeignKey(
        "accounts.Team", on_delete=models.CASCADE, related_name="vault_folders"
    )
    name = models.CharField(max_length=80)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "team", name="vaultfolder_unique_name_per_team"
            )
        ]

    def __str__(self) -> str:
        return self.name


class Credential(BaseModel):
    """Encrypted login credential for a client website resource.

    Usernames, passwords, and notes are stored as Fernet-encrypted binary
    fields.  Plain values are never stored; even the DB column type (BinaryField)
    signals to operators that these are ciphertext blobs, not readable strings.

    The model exposes set_*/get_* pairs to keep encryption transparent to callers.
    """

    class CredentialType(models.TextChoices):
        WORDPRESS = "wordpress", "WordPress Admin"
        WORDPRESS_APP_PASSWORD = (
            "wordpress_app_password",
            "WordPress Application Password",
        )
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
        # SEO / ads / agency tools — the logins the non-dev departments live in.
        GOOGLE_SEARCH_CONSOLE = "google_search_console", "Google Search Console"
        GOOGLE_ANALYTICS = "google_analytics", "Google Analytics"
        GOOGLE_BUSINESS_PROFILE = "google_business_profile", "Google Business Profile"
        GOOGLE_TAG_MANAGER = "google_tag_manager", "Google Tag Manager"
        GOOGLE_ADS = "google_ads", "Google Ads"
        META_BUSINESS = "meta_business", "Meta Business Suite"
        SEMRUSH = "semrush", "Semrush"
        AHREFS = "ahrefs", "Ahrefs"
        # Item kinds that are not website logins. Same encrypted fields, read
        # differently: a note lives in `notes`, an API key in `password`, a
        # server's host in `login_url`, a Wi-Fi network's SSID in `username`.
        SECURE_NOTE = "secure_note", "Secure Note"
        SERVER = "server", "Server / SSH"
        DATABASE = "database", "Database"
        API_KEY = "api_key", "API Key"
        WIFI = "wifi", "Wi-Fi"
        CUSTOM = "custom", "Custom"

    #: Kinds that are not a web sign-in. The extension never offers them in a
    #: page's login dropdown — a server's host or an API's URL can match a
    #: site's domain, and filling an SSH key into a login form is nonsense.
    NON_LOGIN_TYPES = frozenset({"secure_note", "server", "database", "api_key", "wifi"})

    #: The department a credential of each type is filed under when the caller
    #: does not say. Hosting and CMS logins are the dev team's; search and
    #: analytics tools are SEO's; ad platforms are ads'. Custom stays unfiled —
    #: guessing there would put a login in front of a group nobody chose.
    DEFAULT_DEPARTMENT = {
        **{t: "dev" for t in (
            "wordpress", "wordpress_app_password", "cpanel", "godaddy", "namecheap",
            "hostinger", "cloudflare", "ftp", "wix", "webflow", "framer", "shopify",
            "siteground", "bluehost", "wpengine", "kinsta", "server", "database",
        )},
        **{t: "seo" for t in (
            "google_search_console", "google_analytics", "google_business_profile",
            "google_tag_manager", "semrush", "ahrefs",
        )},
        **{t: "ads" for t in ("google_ads", "meta_business")},
    }

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
    # The folder a person filed it in. Null = unfiled.
    folder = models.ForeignKey(
        VaultFolder,
        on_delete=models.SET_NULL,
        related_name="credentials",
        null=True,
        blank=True,
    )
    # The client this credential is for. Follows its website's client; used by
    # the Activity Log's client filter, not shown as a folder.
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.SET_NULL,
        related_name="credentials",
        null=True,
        blank=True,
    )
    # One of `Client.DEPARTMENTS`, or "". Retired as an access route — folders
    # replaced it (credentials/0017 turned department access into folder
    # grants) — and kept only as data.
    department = models.CharField(max_length=20, blank=True, default="", db_index=True)
    label = models.CharField(max_length=200)
    credential_type = models.CharField(
        max_length=30, choices=CredentialType.choices, default=CredentialType.CUSTOM
    )
    login_url = models.URLField(max_length=500, blank=True)

    # Encrypted binary fields — never contain plaintext
    _username = models.BinaryField(blank=True, editable=False)
    _password = models.BinaryField(blank=True, editable=False)
    _notes = models.BinaryField(blank=True, editable=False)
    # Authenticator (TOTP) secret. Never returned by any endpoint — only the
    # current code is (`CredentialService.totp_code`), so a teammate can sign in
    # to a 2FA-protected client account without the secret leaving the server.
    _totp_secret = models.BinaryField(blank=True, editable=False)
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

    # "This login does not work" — reported by whoever hit it, so the next
    # person does not retry a dead password into a lockout. Cleared by a
    # password change (`CredentialService.update`) or by marking it fixed.
    reported_broken_at = models.DateTimeField(null=True, blank=True)
    reported_broken_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reported_broken_note = models.CharField(max_length=300, blank=True, default="")

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
        """Set the password. Callers changing an existing one should go through
        `CredentialService.update`, which keeps the previous value in
        `CredentialPasswordHistory` first."""
        self._password = encryption.encrypt(plaintext)
        self.last_password_changed_at = timezone.now()
        self.password_strength = score_password_strength(plaintext)
        self._rearm_wp_api_reads()

    def _rearm_wp_api_reads(self) -> None:
        """A corrected WordPress credential deserves another try.

        `Website.wp_api_auth_failed_at` disarms the nightly recipient sweep once
        a site rejects us, so nothing would ever retry it again without this —
        the user would fix the password and see no change.
        """
        if not self.website_id or self.credential_type not in (
            self.CredentialType.WORDPRESS,
            self.CredentialType.WORDPRESS_APP_PASSWORD,
        ):
            return

        from apps.websites.models import Website

        Website.objects.filter(pk=self.website_id).update(wp_api_auth_failed_at=None)

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

    def set_totp_secret(self, value: str) -> None:
        """Store (or with "" clear) the authenticator secret. Raises ValueError."""
        secret = normalize_totp_secret(value)
        self._totp_secret = encryption.encrypt(secret) if secret else b""

    def get_totp_secret(self) -> str:
        return encryption.decrypt(bytes(self._totp_secret)) if self._totp_secret else ""

    @property
    def has_totp(self) -> bool:
        return bool(self._totp_secret)


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
        SYSTEM_READ = "system_read", "Read by a scheduled task"
        # Distinct from VIEWED so an autofill pull of a password the dashboard
        # would have hidden is attributable. See the reveal notes in
        # docs/superpowers/specs/2026-09-02-credential-sub-teams-design.md.
        AUTOFILL = "autofill", "Autofilled by the extension"
        TOTP_CODE = "totp_code", "Authenticator code read"
        HISTORY_VIEWED = "history_viewed", "Old password revealed"

    credential = models.ForeignKey(
        Credential,
        on_delete=models.CASCADE,
        related_name="access_logs",
    )
    # Null for a SYSTEM_READ: the scheduled sweep that reads a site's WordPress
    # API has no actor, and inventing one would be a worse record than none.
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
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


class CredentialShareQuerySet(models.QuerySet):
    def active(self):
        """Shares that still grant access: permanent, or not yet expired."""
        return self.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))


class CredentialShare(BaseModel):
    """Grants a developer view+reveal access to a single credential.

    Owners and managers do not need rows here — their access is implicit
    via role.  A creator also does not need a row.  Modification of the
    credential remains gated by `can_modify_credential`.

    `expires_at` makes a share temporary — what an approved access request
    usually creates ("give Ali the hosting login for a day"). Every read of
    shares goes through `.active()`, so an expired row grants nothing even
    before `credentials.purge_expired_shares` deletes it.
    """

    objects = CredentialShareQuerySet.as_manager()

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
    # Null = permanent.
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

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


class SubTeamCredentialGrant(BaseModel):
    """Grants a SubTeam access to credentials. Created by the team owner only.

    Three scopes: every credential in the team, every credential of one
    `credential_type`, or one specific credential. `can_view_password` defaults
    to False, deliberately the opposite of `CredentialShare`, so a grant is
    use-only until the owner widens it on purpose.

    Grants are resolved at query time by `CredentialQuerySet.visible_to`, never
    expanded into per-user rows: a credential created after the grant is
    covered immediately, and moving a member out of the group revokes on their
    next request.
    """

    class Scope(models.TextChoices):
        ALL = "all", "All credentials"
        CREDENTIAL_TYPE = "type", "All credentials of a type"
        CREDENTIAL = "credential", "A single credential"
        FOLDER = "folder", "A folder"

    sub_team = models.ForeignKey(
        "accounts.SubTeam",
        on_delete=models.CASCADE,
        related_name="credential_grants",
    )
    scope = models.CharField(max_length=12, choices=Scope.choices)
    # Set only when scope == CREDENTIAL_TYPE.
    credential_type = models.CharField(max_length=30, blank=True, default="")
    # Set only when scope == CREDENTIAL.
    credential = models.ForeignKey(
        Credential,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sub_team_grants",
    )
    # Set only when scope == FOLDER.
    folder = models.ForeignKey(
        VaultFolder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="grants",
    )
    can_view_password = models.BooleanField(default=False)
    granted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credential_grants_granted",
    )

    class Meta:
        ordering = ["scope", "credential_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["sub_team"],
                condition=Q(scope="all"),
                name="grant_one_blanket_per_subteam",
            ),
            models.UniqueConstraint(
                fields=["sub_team", "credential_type"],
                condition=Q(scope="type"),
                name="grant_unique_type_per_subteam",
            ),
            models.UniqueConstraint(
                fields=["sub_team", "credential"],
                condition=Q(scope="credential"),
                name="grant_unique_credential_per_subteam",
            ),
            models.UniqueConstraint(
                fields=["sub_team", "folder"],
                condition=Q(scope="folder"),
                name="grant_unique_folder_per_subteam",
            ),
        ]
        indexes = [
            models.Index(fields=["sub_team", "scope"], name="grant_subteam_scope_idx"),
        ]

    def __str__(self) -> str:
        target = {
            self.Scope.ALL: "all credentials",
            self.Scope.CREDENTIAL_TYPE: f"type={self.credential_type}",
            self.Scope.CREDENTIAL: f"credential={self.credential_id}",
            self.Scope.FOLDER: f"folder={self.folder_id}",
        }.get(self.scope, self.scope)
        return f"{self.sub_team_id} -> {target}"

    def clean(self):
        """Exactly the field matching `scope` is set, and no cross-team target.

        Also enforced in the serializer, because DRF never calls clean().
        """
        super().clean()
        if self.scope != self.Scope.FOLDER and self.folder_id:
            raise ValidationError({"folder": "Only a folder grant takes a folder."})
        if self.scope == self.Scope.FOLDER:
            if not self.folder_id:
                raise ValidationError({"folder": "Required for a folder grant."})
            if self.credential_type or self.credential_id:
                raise ValidationError("A folder grant takes no other target.")
            if self.folder.team_id != self.sub_team.team_id:
                raise ValidationError({"folder": "That folder belongs to a different team."})
        elif self.scope == self.Scope.ALL:
            if self.credential_type or self.credential_id:
                raise ValidationError(
                    "A grant covering all credentials takes no target."
                )
        elif self.scope == self.Scope.CREDENTIAL_TYPE:
            if not self.credential_type:
                raise ValidationError(
                    {"credential_type": "Required for a credential-type grant."}
                )
            if self.credential_id:
                raise ValidationError(
                    {"credential": "Not allowed on a credential-type grant."}
                )
        elif self.scope == self.Scope.CREDENTIAL:
            if not self.credential_id:
                raise ValidationError(
                    {"credential": "Required for a single-credential grant."}
                )
            if self.credential_type:
                raise ValidationError(
                    {"credential_type": "Not allowed on a single-credential grant."}
                )
            if self.credential.team_id != self.sub_team.team_id:
                raise ValidationError(
                    {"credential": "That credential belongs to a different team."}
                )


class CredentialAccessRequest(BaseModel):
    """A member asking for a credential they cannot see.

    Replaces "can someone send me the hosting login" in a chat, which is how
    passwords leak inside an agency: the request is visible, approved by
    someone who may share the credential (`can_modify_credential`), usually for
    a fixed time, and the grant it produces is an ordinary `CredentialShare`
    with `expires_at` — so every existing access check already understands it.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        CANCELLED = "cancelled", "Cancelled"

    #: Durations offered to requester and approver, in hours. None = permanent.
    DURATION_CHOICES = (4, 24, 24 * 7, None)

    team = models.ForeignKey(
        "accounts.Team", on_delete=models.CASCADE, related_name="credential_access_requests"
    )
    credential = models.ForeignKey(
        Credential, on_delete=models.CASCADE, related_name="access_requests"
    )
    requester = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="credential_access_requests"
    )
    reason = models.CharField(max_length=300, blank=True, default="")
    # What the requester asked for; the approver may change it. Null = permanent.
    requested_hours = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    decided_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credential_access_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True, default="")
    # Copied from the share the approval created, for the request history.
    granted_until = models.DateTimeField(null=True, blank=True)
    can_view_password = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["credential", "requester"],
                condition=Q(status="pending"),
                name="one_pending_access_request_per_user",
            )
        ]

    def __str__(self) -> str:
        return f"{self.requester_id} -> {self.credential_id} ({self.status})"


class CredentialPasswordHistory(BaseModel):
    """A password this credential used to have, encrypted like the live one.

    Written by `CredentialService.update` just before a change, so the vault
    can answer "what was it before Ali changed it on Tuesday?" — the common
    agency emergency, when a client's site breaks after someone rotated a login
    and the old one is still configured somewhere. Capped at `KEEP` per
    credential; the oldest go first.
    """

    KEEP = 10

    credential = models.ForeignKey(
        Credential, on_delete=models.CASCADE, related_name="password_history"
    )
    _password = models.BinaryField(editable=False)
    # Who replaced this password (i.e. made the change that retired it).
    changed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # When this password was set, if known, so the list can say how long it lived.
    set_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["credential", "-created_at"])]

    def get_password(self) -> str:
        return encryption.decrypt(bytes(self._password)) if self._password else ""


class FolderShare(BaseModel):
    """A folder shared with one person — every login filed in it, now or later.

    The point of folders for the team: hand Amar the 51 logins in "SEO" in one
    step instead of 51, and have the 52nd reach him the moment it is filed. The
    group version is a FOLDER-scope `SubTeamCredentialGrant`; this is the same
    thing for a single person. Use-only unless `can_view_password`, like every
    other share.
    """

    folder = models.ForeignKey(VaultFolder, on_delete=models.CASCADE, related_name="shares")
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="folder_shares"
    )
    can_view_password = models.BooleanField(default=False)
    shared_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["folder", "user"], name="foldershare_unique_per_user")
        ]

    def __str__(self) -> str:
        return f"{self.folder_id} -> {self.user_id}"
