from django.db import models

from apps.common.models import BaseModel
from apps.common.querysets import TeamScopedQuerySet


class Client(BaseModel):
    """Tracks a client's hosting, access, and operational details.

    Maps 1-to-1 with a ClickUp task when clickup_task_id is set.
    Soft-deleted via status=INACTIVE — never hard-deleted.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

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

    class MigrationStatus(models.TextChoices):
        NOT_DONE = "not_done", "No - We didn't do"
        DONE_TO_SG = "done_to_siteground", "Yes - From WPEngine to SiteGround"
        NOT_APPLICABLE = "not_applicable", "N/A"

    class MigrationConfirmation(models.TextChoices):
        CAN_DO = "can_do", "Yes, We can do Migration"
        CANNOT = "cannot", "No, We can't"
        UNKNOWN = "", "Unknown"

    class PpcStatus(models.TextChoices):
        YES = "yes", "Yes"
        NO = "no", "No"
        UNKNOWN = "", "Unknown"

    class SupportTier(models.TextChoices):
        NONE = "", "None"
        BASIC = "basic", "Basic"
        STANDARD = "standard", "Standard"
        PREMIUM = "premium", "Premium"

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

    hosting_platform = models.CharField(max_length=30, blank=True, default="")
    hosting_renewal_date = models.DateField(null=True, blank=True)
    domain_access_location = models.CharField(max_length=200, blank=True)
    migration_status = models.CharField(max_length=30, blank=True, default="")
    csm_migration_confirmation = models.CharField(max_length=30, blank=True, default="")
    running_ppc_ads = models.CharField(max_length=10, blank=True, default="")
    website_built_by_digi = models.CharField(max_length=50, blank=True, default="")
    website_maintained_by_digi = models.CharField(max_length=50, blank=True, default="")
    notes = models.TextField(blank=True)
    comments = models.TextField(blank=True)

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
    support_tier = models.CharField(
        max_length=20, choices=SupportTier.choices, blank=True, default=""
    )
    contract_renewal_date = models.DateField(null=True, blank=True)

    clickup_task_id = models.CharField(max_length=64, blank=True, db_index=True)
    clickup_synced_at = models.DateTimeField(null=True, blank=True)

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
