from django.db import models

from apps.common.models import BaseModel


class DomainInfo(BaseModel):
    """Cached WHOIS, hosting, and SSL data for a client website.

    One-to-one with Website.  Updated daily by the domain_check Celery task.
    """

    website = models.OneToOneField(
        "websites.Website",
        on_delete=models.CASCADE,
        related_name="domain_info",
    )

    # WHOIS
    registrar = models.CharField(max_length=200, blank=True)
    registered_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    nameservers = models.JSONField(default=list)
    whois_privacy = models.BooleanField(null=True, blank=True)
    auto_renew = models.BooleanField(null=True, blank=True)

    # Hosting
    hosting_provider = models.CharField(max_length=200, blank=True)
    hosting_ip = models.GenericIPAddressField(null=True, blank=True)
    server_location = models.CharField(max_length=100, blank=True)
    uses_cloudflare = models.BooleanField(default=False)

    # SSL
    ssl_issuer = models.CharField(max_length=200, blank=True)
    ssl_expires_at = models.DateTimeField(null=True, blank=True)
    ssl_auto_renew = models.BooleanField(null=True, blank=True)

    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"DomainInfo({self.website.domain})"

    @property
    def domain_days_until_expiry(self) -> int | None:
        if not self.expires_at:
            return None
        from django.utils import timezone
        delta = self.expires_at - timezone.now()
        return max(0, delta.days)

    @property
    def ssl_days_until_expiry(self) -> int | None:
        if not self.ssl_expires_at:
            return None
        from django.utils import timezone
        delta = self.ssl_expires_at - timezone.now()
        return max(0, delta.days)


class DomainAlert(BaseModel):
    """A pending or sent expiry alert for a domain or SSL certificate."""

    class AlertType(models.TextChoices):
        DOMAIN = "domain", "Domain Expiry"
        SSL = "ssl", "SSL Expiry"

    domain_info = models.ForeignKey(
        DomainInfo,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    alert_type = models.CharField(max_length=10, choices=AlertType.choices)
    days_until_expiry = models.IntegerField()
    sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        # One alert per (domain, type, threshold) — prevents duplicate sends
        unique_together = [("domain_info", "alert_type", "days_until_expiry")]

    def __str__(self) -> str:
        return (
            f"{self.alert_type} alert ({self.days_until_expiry}d) "
            f"for {self.domain_info.website.domain}"
        )
