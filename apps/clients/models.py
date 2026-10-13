from django.db import models

from apps.common.models import BaseModel
from apps.common.querysets import TeamScopedQuerySet


class Client(BaseModel):
    """Tracks a client's hosting, access, and operational details.

    Retired via status=OFFBOARDED, which is reversible and keeps the history.
    An offboarded client can then be hard-deleted (DELETE on the detail
    endpoint) to clear out rows that should never have existed - a client
    filed twice under different capitalisation, say. An active one cannot.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        OFFBOARDED = "offboarded", "Offboarded"

    class HostingPlatform(models.TextChoices):
        WPENGINE = "wpengine", "WPEngine"
        SITEGROUND = "siteground", "SiteGround"
        CLOUDWAYS = "cloudways", "Cloudways"
        BLUEHOST = "bluehost", "Bluehost"
        GODADDY = "godaddy", "GoDaddy"
        SQUARESPACE = "squarespace", "Squarespace"
        WIXCOM = "wix", "Wix"
        SHOPIFY = "shopify", "Shopify"
        OTHER = "other", "Other"
        UNKNOWN = "", "Unknown"

    class PpcStatus(models.TextChoices):
        YES = "yes", "Yes"
        NO = "no", "No"
        UNKNOWN = "", "Unknown"

    class Tier(models.TextChoices):
        GOLD = "gold", "Gold"
        SILVER = "silver", "Silver"
        BRONZE = "bronze", "Bronze"
        NONE = "", "None"

    class WebsiteAccessLevel(models.TextChoices):
        FULL_ADMIN = "full_admin", "Full admin"
        DELEGATE = "delegate", "Delegate access"
        NONE = "none", "No access"
        # Credentials exist but don't get us in — distinct from "No access",
        # which means we were never given any.
        NOT_WORKING = "not_working", "Access not working"
        UNKNOWN = "", "Unknown"

    # Departments that may work on this client — controls who sees it (Phase 7).
    # Stored in the `departments` JSONField, so adding a value here needs no
    # migration; it widens the serializer's ChoiceField and the CSV import.
    DEPARTMENTS = (
        "seo", "ads", "dev", "content", "lead_insight", "social_media",
    )

    team = models.ForeignKey(
        "accounts.Team",
        on_delete=models.CASCADE,
        related_name="clients",
    )
    name = models.CharField(max_length=200, db_index=True)
    website_url = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    tier = models.CharField(max_length=20, choices=Tier.choices, blank=True, default="")

    hosting_platform = models.CharField(max_length=30, blank=True, default="")
    # Free-text platform name, used when hosting_platform == "other".
    hosting_platform_other = models.CharField(max_length=100, blank=True, default="")
    hosting_renewal_date = models.DateField(null=True, blank=True)
    domain_renewal_date = models.DateField(null=True, blank=True)
    domain_access_location = models.CharField(max_length=200, blank=True)
    website_access_level = models.CharField(
        max_length=20, choices=WebsiteAccessLevel.choices, blank=True, default=""
    )
    # Subset of DEPARTMENTS, e.g. ["seo", "ads"].
    departments = models.JSONField(default=list, blank=True)
    running_ppc_ads = models.CharField(max_length=10, blank=True, default="")
    website_built_by_us = models.CharField(max_length=50, blank=True, default="")
    website_maintained_by_us = models.CharField(max_length=50, blank=True, default="")
    notes = models.TextField(blank=True)

    # Per-client notification toggles, honored by alert delivery.
    notify_desktop = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=True)

    # Commercial / ownership (Phase 2.5)
    assigned_to = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_clients",
    )
    monthly_revenue = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    objects = TeamScopedQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["team", "status"]),
            models.Index(fields=["website_url"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.website_url})"

    @property
    def domain(self) -> str:
        url = self.website_url.lower().strip()
        for prefix in ("https://", "http://", "www."):
            url = url.removeprefix(prefix)
        return url.rstrip("/")
