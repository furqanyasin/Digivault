import secrets
import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.text import slugify

from apps.accounts.managers import UserManager
from apps.common.models import BaseModel
from apps.credentials import encryption as _enc


class User(AbstractUser):
    """Custom user model. Email is the login identifier; username mirrors it.

    Extends AbstractUser so Django's auth plumbing (permissions, admin) works
    out of the box.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    # username kept for Django internals but never shown in the UI
    username = models.CharField(max_length=254, unique=True)

    profile_photo = models.ImageField(
        upload_to="profiles/", null=True, blank=True
    )
    timezone = models.CharField(max_length=50, default="UTC")

    # The team the user is currently "acting as" — set at login or team switch.
    # Nullable because a freshly registered user has no team yet.
    active_team = models.ForeignKey(
        "accounts.Team",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    # 2FA — TOTP via Google Authenticator
    totp_secret = models.BinaryField(blank=True, editable=False)
    totp_enabled = models.BooleanField(default=False)
    totp_backup_codes = models.JSONField(default=list, blank=True)

    # Set when an admin creates the account with a temporary password; forces a
    # password change on first login before any other access.
    must_change_password = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # email is already required by USERNAME_FIELD

    objects = UserManager()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email


class Team(BaseModel):
    """Represents a web agency or freelancer account.

    A user can be a member of multiple teams but has exactly one active_team at
    a time. All client data (websites, scripts, credentials) is scoped to a team.
    """

    class Plan(models.TextChoices):
        STARTER = "starter", "Starter"
        AGENCY = "agency", "Agency"
        AGENCY_PRO = "agency_pro", "Agency Pro"
        ENTERPRISE = "enterprise", "Enterprise"

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    owner = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="owned_teams",
    )
    plan = models.CharField(
        max_length=20, choices=Plan.choices, default=Plan.STARTER
    )
    _clickup_api_token = models.BinaryField(blank=True, editable=False)

    @property
    def clickup_api_token(self) -> str:
        if not self._clickup_api_token:
            return ""
        try:
            return _enc.decrypt(bytes(self._clickup_api_token))
        except Exception:
            return ""

    @clickup_api_token.setter
    def clickup_api_token(self, value: str) -> None:
        self._clickup_api_token = _enc.encrypt(value) if value else b""

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)
        # Ensure owner always has an owner-level membership
        TeamMembership.objects.get_or_create(
            user=self.owner,
            team=self,
            defaults={"role": TeamMembership.Role.OWNER},
        )

    def _generate_unique_slug(self) -> str:
        base = slugify(self.name)
        slug = base
        counter = 1
        while Team.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug


class TeamMembership(BaseModel):
    """Links a User to a Team with an assigned role."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"
        DEVELOPER = "developer", "Developer"
        VIEWER = "viewer", "Viewer"
        # Per-member feature access — allowed sections live in `feature_access`.
        CUSTOM = "custom", "Custom"
        # Legacy member-level roles — no longer offered in the UI, kept so any
        # existing memberships stay valid.
        EDITOR = "editor", "Editor"
        SEO = "seo", "SEO"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="memberships"
    )
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.DEVELOPER
    )
    # When role == "custom", the list of feature keys this member may access
    # (e.g. ["websites", "reports"]). Ignored for every other role.
    feature_access = models.JSONField(default=list, blank=True)

    class Meta:
        unique_together = [("user", "team")]
        ordering = ["team", "role"]

    def __str__(self) -> str:
        return f"{self.user.email} — {self.team.name} ({self.role})"


class PasswordResetRequest(BaseModel):
    """Admin-gated password reset request.

    Flow: user submits email → record created (PENDING) →
    admin approves (APPROVED, reset token sent) or rejects (REJECTED) →
    user visits reset link → sets new password → token cleared.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        USED = "used", "Used"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="password_reset_requests",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    reset_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_password_resets",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"PasswordReset({self.user.email}, {self.status})"


class TeamInvitation(BaseModel):
    """Pending email invitation to join a team."""

    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="invitations"
    )
    invited_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sent_invitations"
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=20,
        choices=TeamMembership.Role.choices,
        default=TeamMembership.Role.DEVELOPER,
    )
    token = models.CharField(max_length=64, unique=True, blank=True)
    accepted = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("team", "email")]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(48)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Invitation for {self.email} to {self.team.name}"
