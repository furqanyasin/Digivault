"""Backfill: mirror existing clients' hosting renewal dates onto their websites.

New clients sync hosting_renewal_date -> website DomainInfo.hosting_expires_at on
save, but clients created before that need a one-time backfill so the date shows
on the Access & Domain tab without re-saving each one.
"""

from datetime import datetime, time

from django.db import migrations
from django.db.models import Q
from django.utils import timezone


def _normalize_domain(url: str) -> str:
    s = (url or "").lower().strip()
    for prefix in ("https://", "http://", "www."):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s.split("/")[0].rstrip("/")


def backfill(apps, schema_editor):
    Client = apps.get_model("clients", "Client")
    Website = apps.get_model("websites", "Website")
    DomainInfo = apps.get_model("domains", "DomainInfo")

    aware = timezone.is_aware(timezone.now())

    for client in Client.objects.exclude(hosting_renewal_date__isnull=True):
        dt = datetime.combine(client.hosting_renewal_date, time.min)
        if aware:
            dt = timezone.make_aware(dt)
        domain = _normalize_domain(client.website_url)
        websites = Website.objects.filter(team_id=client.team_id).filter(
            Q(client_id=client.id) | (Q(domain__iexact=domain) if domain else Q(pk__in=[]))
        )
        for w in websites:
            di, _ = DomainInfo.objects.get_or_create(website=w)
            if di.hosting_expires_at != dt:
                di.hosting_expires_at = dt
                di.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("clients", "0003_client_assigned_to_client_contract_renewal_date_and_more"),
        ("websites", "0003_add_client_fk"),
        ("domains", "0003_domaininfo_hosting_expires_at_domaininfo_mx_hosts_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
