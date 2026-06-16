"""Hosting expiry (manual) + SMTP status checks."""
import datetime

import pytest
from django.utils import timezone

from apps.domains.models import DomainAlert, DomainInfo
from apps.domains.services import check_smtp
from apps.websites.models import Website


# --- SMTP checker (pure, injected resolver/probe) ---

def test_check_smtp_ok():
    r = check_smtp("acme.com", resolve_mx=lambda d: ["mx1.acme.com"], probe=lambda h: True)
    assert r["smtp_status"] == "ok"
    assert r["mx_hosts"] == ["mx1.acme.com"]


def test_check_smtp_no_mx():
    r = check_smtp("acme.com", resolve_mx=lambda d: [], probe=lambda h: True)
    assert r["smtp_status"] == "no_mx"


def test_check_smtp_unreachable():
    r = check_smtp("acme.com", resolve_mx=lambda d: ["mx1.acme.com"], probe=lambda h: False)
    assert r["smtp_status"] == "unreachable"


def test_check_smtp_resolver_error():
    def _boom(d):
        raise OSError("dns fail")
    r = check_smtp("acme.com", resolve_mx=_boom, probe=lambda h: True)
    assert r["smtp_status"] == "error"


# --- Hosting expiry endpoint ---

@pytest.mark.django_db
def test_patch_sets_hosting_expiry(auth_client, team):
    w = Website.objects.create(team=team, name="H", domain="host.example")
    future = (timezone.now() + datetime.timedelta(days=200)).date().isoformat()
    resp = auth_client.patch(
        f"/api/v1/websites/{w.id}/domain/", {"hosting_expires_at": future}, format="json"
    )
    assert resp.status_code == 200
    info = DomainInfo.objects.get(website=w)
    assert info.hosting_expires_at is not None
    assert info.hosting_days_until_expiry is not None


@pytest.mark.django_db
def test_patch_hosting_expiry_creates_alert_when_near(auth_client, team):
    w = Website.objects.create(team=team, name="H", domain="host2.example")
    soon = (timezone.now() + datetime.timedelta(days=5)).date().isoformat()
    auth_client.patch(
        f"/api/v1/websites/{w.id}/domain/", {"hosting_expires_at": soon}, format="json"
    )
    info = DomainInfo.objects.get(website=w)
    assert info.alerts.filter(alert_type=DomainAlert.AlertType.HOSTING).exists()


@pytest.mark.django_db
def test_patch_clears_hosting_expiry(auth_client, team):
    w = Website.objects.create(team=team, name="H", domain="host3.example")
    DomainInfo.objects.create(website=w, hosting_expires_at=timezone.now())
    resp = auth_client.patch(
        f"/api/v1/websites/{w.id}/domain/", {"hosting_expires_at": None}, format="json"
    )
    assert resp.status_code == 200
    info = DomainInfo.objects.get(website=w)
    assert info.hosting_expires_at is None
