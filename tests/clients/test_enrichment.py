"""Client profile enrichment (assignment, revenue, tier) and feedback-round fields."""

import datetime
from decimal import Decimal

import pytest

from apps.clients.models import Client
from apps.clients.serializers import ClientSerializer
from apps.websites.models import Website


@pytest.mark.django_db
def test_new_fields_persist_and_serialize(team, user):
    client = Client.objects.create(
        team=team,
        name="Acme",
        website_url="https://acme.io",
        assigned_to=user,
        monthly_revenue=Decimal("1500.00"),
        tier=Client.Tier.GOLD,
        website_access_level=Client.WebsiteAccessLevel.DELEGATE,
        departments=["seo", "ads"],
        hosting_platform="other",
        hosting_platform_other="Krystal Hosting",
        domain_renewal_date=datetime.date(2027, 1, 1),
        notify_desktop=False,
    )
    Website.objects.create(team=team, name="Acme Site", domain="acme.io", client=client)

    data = ClientSerializer(client).data
    assert data["tier"] == "gold"
    assert data["monthly_revenue"] == "1500.00"
    assert data["website_access_level"] == "delegate"
    assert data["departments"] == ["seo", "ads"]
    assert data["hosting_platform_other"] == "Krystal Hosting"
    assert data["domain_renewal_date"] == "2027-01-01"
    assert data["notify_desktop"] is False
    assert data["notify_email"] is True
    assert data["assigned_to"] == user.id
    assert data["assigned_websites_count"] == 1


@pytest.mark.django_db
def test_blank_name_rejected(auth_client, team):
    resp = auth_client.post(
        "/api/v1/clients/",
        {"name": "", "website_url": "https://x.io"},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_status_choices_paused_and_offboarded(auth_client, team):
    c = Client.objects.create(team=team, name="Pause Co")
    resp = auth_client.patch(
        f"/api/v1/clients/{c.id}/", {"status": "paused"}, format="json"
    )
    assert resp.status_code == 200, resp.data
    c.refresh_from_db()
    assert c.status == "paused"

    resp = auth_client.post(f"/api/v1/clients/{c.id}/deactivate/")
    assert resp.status_code == 200
    c.refresh_from_db()
    assert c.status == "offboarded"
