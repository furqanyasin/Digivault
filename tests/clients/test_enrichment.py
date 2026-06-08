"""Phase 2.5 — client profile enrichment (assignment, revenue, tier, renewal)."""

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
        support_tier=Client.SupportTier.PREMIUM,
        contract_renewal_date=datetime.date(2027, 1, 1),
    )
    Website.objects.create(team=team, name="Acme Site", domain="acme.io", client=client)

    data = ClientSerializer(client).data
    assert data["support_tier"] == "premium"
    assert data["monthly_revenue"] == "1500.00"
    assert data["contract_renewal_date"] == "2027-01-01"
    assert data["assigned_to"] == user.id
    assert data["assigned_websites_count"] == 1
