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
    # Manually entered — hosting renewal is not discoverable via WHOIS/DNS.
    hosting_expires_at = models.DateTimeField(null=True, blank=True)

    # Mail (SMTP) — populated by the daily domain check.
    smtp_status = models.CharField(max_length=20, blank=True)  # ok/unreachable/no_mx/error
    mx_hosts = models.JSONField(default=list, blank=True)
    smtp_checked_at = models.DateTimeField(null=True, blank=True)

    # Email authentication — SPF/DKIM/DMARC, from the same daily check. Status is
    # pass/missing/error and describes presence and syntax, not correctness:
    # proving an SPF policy lists the right senders needs the sending
    # infrastructure, which we don't know. Records are kept for display.
    spf_status = models.CharField(max_length=10, blank=True)
    spf_record = models.CharField(max_length=500, blank=True)
    dmarc_status = models.CharField(max_length=10, blank=True)
    dmarc_record = models.CharField(max_length=500, blank=True)
    dkim_status = models.CharField(max_length=10, blank=True)
    # Which selector answered — DKIM selectors aren't discoverable, so this
    # records the one that worked out of the probed list.
    dkim_selector = models.CharField(max_length=60, blank=True)

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

    @property
    def hosting_days_until_expiry(self) -> int | None:
        if not self.hosting_expires_at:
            return None
        from django.utils import timezone
        delta = self.hosting_expires_at - timezone.now()
        return max(0, delta.days)


class DomainAlert(BaseModel):
    """A pending or sent expiry alert for a domain or SSL certificate."""

    class AlertType(models.TextChoices):
        DOMAIN = "domain", "Domain Expiry"
        SSL = "ssl", "SSL Expiry"
        HOSTING = "hosting", "Hosting Expiry"

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
